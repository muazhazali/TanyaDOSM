"""FastAPI application and SSE transport."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from askdosm.agent import TanyaDOSMService
from askdosm.api.manager import RunManager
from askdosm.api.models import HealthStatus, RunCreateRequest, RunSnapshot, RunSummary, TERMINAL_STATUSES
from askdosm.api.store import RunStore
from askdosm.catalogue import Catalogue
from askdosm.config import Settings, get_settings
from askdosm.data import DatasetCache
from askdosm.monitor import CatalogueMonitor, MonitorState
from askdosm.providers import check_cloudflare, check_groq


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, service_factory=None) -> FastAPI:
    config = settings or get_settings()
    uses_default_service = service_factory is None
    store = RunStore(config.run_db_path)
    factory = service_factory or (lambda: TanyaDOSMService(config))
    manager = RunManager(store, factory, config.run_retention_days)
    monitor = CatalogueMonitor(
        Catalogue(config.catalogue_path),
        DatasetCache(config.cache_dir / "datasets", config.cache_ttl_hours),
        config.cache_dir / "catalogue-monitor.json",
    )
    monitor_lock = asyncio.Lock()
    health_cache: dict[str, object] = {"checked_at": 0.0, "llm": "unavailable", "embeddings": "unavailable"}
    health_lock = asyncio.Lock()

    async def check_catalogue() -> MonitorState:
        async with monitor_lock:
            return await asyncio.to_thread(monitor.check)

    async def monitor_loop() -> None:
        while True:
            try:
                await check_catalogue()
            except Exception:
                logger.exception("Catalogue monitoring cycle failed")
            await asyncio.sleep(config.monitor_interval_hours * 3600)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if uses_default_service:
            config.require_groq_credentials()
        application.state.store = store
        application.state.manager = manager
        application.state.monitor = monitor
        await manager.start()
        monitor_task = asyncio.create_task(monitor_loop(), name="askdosm-catalogue-monitor")
        yield
        monitor_task.cancel()
        with suppress(asyncio.CancelledError):
            await monitor_task
        await manager.stop()

    app = FastAPI(title="TanyaDOSM API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.get("/api/health", response_model=HealthStatus)
    async def health() -> HealthStatus:
        try:
            Catalogue(config.catalogue_path)
            catalogue_status = "ready"
        except Exception:
            catalogue_status = "unavailable"

        async with health_lock:
            now = monotonic()
            if now - float(health_cache["checked_at"]) >= 30:
                llm_status, embedding_status = await asyncio.gather(
                    asyncio.to_thread(check_groq, config),
                    asyncio.to_thread(check_cloudflare, config),
                )
                health_cache.update(
                    checked_at=now,
                    llm=llm_status,
                    embeddings=embedding_status,
                )
        llm_status = str(health_cache["llm"])
        embedding_status = str(health_cache["embeddings"])
        overall = "ready" if catalogue_status == llm_status == embedding_status == "ready" else "degraded"
        return HealthStatus(
            status=overall,
            database="ready",
            catalogue=catalogue_status,
            llm=llm_status,
            embeddings=embedding_status,
        )

    @app.get("/api/datasets")
    async def datasets():
        return [
            item.model_dump(mode="json", exclude={"parquet_url", "expected_schema", "default_filters"})
            for item in Catalogue(config.catalogue_path).all()
        ]

    @app.get("/api/catalogue-monitor", response_model=MonitorState)
    async def catalogue_monitor() -> MonitorState:
        return await asyncio.to_thread(monitor.read_state)

    @app.post("/api/catalogue-monitor/check", response_model=MonitorState)
    async def check_catalogue_now() -> MonitorState:
        return await check_catalogue()

    @app.post("/api/runs", response_model=RunSnapshot, status_code=status.HTTP_202_ACCEPTED)
    async def create_run(body: RunCreateRequest) -> RunSnapshot:
        if len(body.question) > config.max_question_length:
            raise HTTPException(status_code=422, detail="Question is too long")
        return await manager.create(body.question)

    @app.get("/api/runs", response_model=list[RunSummary])
    async def list_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[RunSummary]:
        return await store.list_runs(limit)

    @app.get("/api/runs/{run_id}", response_model=RunSnapshot)
    async def get_run(run_id: str) -> RunSnapshot:
        snapshot = await store.get_run(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return snapshot

    @app.get("/api/runs/{run_id}/events")
    async def stream_events(
        run_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        if await store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
        try:
            cursor = max(after, int(last_event_id or 0))
        except ValueError:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from None

        async def generate():
            nonlocal cursor
            idle_ticks = 0
            while not await request.is_disconnected():
                events = await store.get_events(run_id, cursor)
                for event in events:
                    cursor = event.sequence
                    yield f"id: {event.sequence}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
                snapshot = await store.get_run(run_id)
                if snapshot and snapshot.status in TERMINAL_STATUSES and not events:
                    break
                idle_ticks += 1
                if idle_ticks % 30 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @app.delete("/api/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_run(run_id: str):
        try:
            deleted = await store.delete_run(run_id)
        except RuntimeError:
            raise HTTPException(status_code=409, detail="Active runs cannot be deleted") from None
        if not deleted:
            raise HTTPException(status_code=404, detail="Run not found")
        return None

    dist = Path("frontend/dist")
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        async def root():
            return JSONResponse({"name": "TanyaDOSM API", "frontend": "Run pnpm build in frontend/"})

    return app


app = create_app()
