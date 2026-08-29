"""Single-concurrency run queue connecting LangGraph to durable API events."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from uuid import uuid4

from askdosm.agent import TanyaDOSMService
from askdosm.api.models import RunSnapshot, RunStatus
from askdosm.api.store import RunStore
from askdosm.providers import HostedProviderError


class RunManager:
    def __init__(self, store: RunStore, service_factory: Callable[[], TanyaDOSMService], retention_days: int = 7):
        self.store = store
        self.service_factory = service_factory
        self.retention_days = retention_days
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._maintenance: asyncio.Task | None = None
        self._service: TanyaDOSMService | None = None
        self._cancelled: set[str] = set()
        self._active_run_id: str | None = None

    async def start(self) -> None:
        await self.store.initialize()
        await self.store.interrupt_active()
        await self.store.cleanup(self.retention_days)
        self._worker = asyncio.create_task(self._work(), name="askdosm-run-worker")
        self._maintenance = asyncio.create_task(self._maintain(), name="askdosm-retention-worker")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker
        if self._maintenance:
            self._maintenance.cancel()
            with suppress(asyncio.CancelledError):
                await self._maintenance

    async def create(self, question: str, conversation_id: str | None = None) -> RunSnapshot:
        run_id = uuid4().hex
        snapshot = await self.store.create_run(run_id, question, conversation_id)
        await self.store.append_event(run_id, {"type": "run.queued", "payload": {}})
        await self.queue.put(run_id)
        refreshed = await self.store.get_run(run_id)
        return refreshed or snapshot

    def queue_position(self, run_id: str) -> int | None:
        if run_id == self._active_run_id:
            return 0
        queued = [item for item in list(self.queue._queue) if item not in self._cancelled]
        try:
            return queued.index(run_id) + 1
        except ValueError:
            return None

    async def cancel(self, run_id: str) -> bool:
        snapshot = await self.store.get_run(run_id)
        if snapshot is None:
            return False
        if snapshot.status != RunStatus.QUEUED:
            raise RuntimeError("not_queued")
        self._cancelled.add(run_id)
        await self.store.update_status(
            run_id, RunStatus.INTERRUPTED, error="This request was cancelled before it started."
        )
        await self.store.append_event(
            run_id, {"type": "run.failed", "payload": {"error": "Request cancelled"}}
        )
        return True

    async def _work(self) -> None:
        while True:
            run_id = await self.queue.get()
            try:
                if run_id in self._cancelled:
                    self._cancelled.discard(run_id)
                    continue
                await self._execute(run_id)
            finally:
                self.queue.task_done()

    async def _maintain(self) -> None:
        while True:
            await asyncio.sleep(3600)
            await self.store.cleanup(self.retention_days)

    async def _execute(self, run_id: str) -> None:
        snapshot = await self.store.get_run(run_id)
        if snapshot is None or snapshot.status != RunStatus.QUEUED:
            return
        self._active_run_id = run_id
        await self.store.update_status(run_id, RunStatus.RUNNING)
        await self.store.append_event(run_id, {"type": "run.started", "payload": {}})
        loop = asyncio.get_running_loop()

        def sink(event: dict) -> None:
            future = asyncio.run_coroutine_threadsafe(self.store.append_event(run_id, event), loop)
            future.result()

        try:
            if self._service is None:
                self._service = await asyncio.to_thread(self.service_factory)
            history = await self.store.get_context(
                snapshot.conversation_id, exclude_run_id=run_id
            )
            resolved_question = snapshot.question
            if history:
                resolved_question = await asyncio.to_thread(
                    self._service.resolve_question, snapshot.question, history
                )
                await self.store.append_event(
                    run_id,
                    {"type": "context.resolved", "payload": {"question": resolved_question}},
                )
            await self.store.set_resolved_question(run_id, resolved_question)
            answer = await asyncio.to_thread(self._service.ask, resolved_question, event_sink=sink)
            await self.store.update_status(run_id, RunStatus.COMPLETED, answer=answer)
            await self.store.append_event(
                run_id, {"type": "run.completed", "payload": {"has_error": answer.error is not None}}
            )
        except HostedProviderError as exc:
            message = str(exc)
            await self.store.update_status(run_id, RunStatus.FAILED, error=message)
            await self.store.append_event(
                run_id, {"type": "run.failed", "payload": {"error": message}}
            )
        except Exception as exc:
            message = f"TanyaDOSM could not complete this run ({type(exc).__name__})."
            await self.store.update_status(run_id, RunStatus.FAILED, error=message)
            await self.store.append_event(
                run_id, {"type": "run.failed", "payload": {"error": message}}
            )
        finally:
            self._active_run_id = None
