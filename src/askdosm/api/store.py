"""Durable SQLite storage for independent AskDOSM runs and events."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from askdosm.api.models import RunEvent, RunSnapshot, RunStatus, RunSummary, TERMINAL_STATUSES
from askdosm.models import AnswerPayload


def utcnow() -> datetime:
    return datetime.now(UTC)


def _event_payload(value: Any) -> dict[str, Any]:
    """Keep the public event contract stable, including for legacy rows."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return {"items": value}


class RunStore:
    def __init__(self, path: Path):
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_node TEXT,
                    answer_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    node TEXT,
                    duration_ms REAL,
                    payload_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence),
                    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_runs_updated_at ON runs(updated_at DESC);
                """
            )
            await db.commit()

    async def create_run(self, run_id: str, question: str) -> RunSnapshot:
        now = utcnow().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO runs (id, question, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (run_id, question, RunStatus.QUEUED.value, now, now),
            )
            await db.commit()
        snapshot = await self.get_run(run_id)
        assert snapshot is not None
        return snapshot

    async def get_run(self, run_id: str) -> RunSnapshot | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await db.execute_fetchall(
                """SELECT r.*, COALESCE(MAX(e.sequence), 0) AS last_sequence
                   FROM runs r LEFT JOIN run_events e ON e.run_id = r.id
                   WHERE r.id = ? GROUP BY r.id""",
                (run_id,),
            )
        return self._snapshot(row[0]) if row else None

    async def list_runs(self, limit: int = 20) -> list[RunSummary]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM runs ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        return [self._summary(row) for row in rows]

    async def update_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        current_node: str | None = None,
        answer: AnswerPayload | None = None,
        error: str | None = None,
    ) -> None:
        answer_json = answer.model_dump_json() if answer else None
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """UPDATE runs SET status = ?, current_node = COALESCE(?, current_node),
                   answer_json = COALESCE(?, answer_json), error = ?, updated_at = ? WHERE id = ?""",
                (status.value, current_node, answer_json, error, utcnow().isoformat(), run_id),
            )
            await db.commit()

    async def append_event(self, run_id: str, event: dict[str, Any]) -> RunEvent:
        timestamp = utcnow()
        payload = _event_payload(event.get("payload"))
        # Round-trip through JSON here so non-serializable state can never reach storage.
        payload_json = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM run_events WHERE run_id = ?", (run_id,)
            )
            sequence = int((await cursor.fetchone())[0])
            await db.execute(
                """INSERT INTO run_events
                   (run_id, sequence, type, node, duration_ms, payload_json, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    sequence,
                    event["type"],
                    event.get("node"),
                    event.get("duration_ms"),
                    payload_json,
                    timestamp.isoformat(),
                ),
            )
            await db.execute(
                "UPDATE runs SET current_node = COALESCE(?, current_node), updated_at = ? WHERE id = ?",
                (event.get("node"), timestamp.isoformat(), run_id),
            )
            await db.commit()
        return RunEvent(
            run_id=run_id,
            sequence=sequence,
            type=event["type"],
            node=event.get("node"),
            duration_ms=event.get("duration_ms"),
            payload=json.loads(payload_json),
            timestamp=timestamp,
        )

    async def get_events(self, run_id: str, after: int = 0) -> list[RunEvent]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM run_events WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, after),
            )
        return [
            RunEvent(
                run_id=row["run_id"],
                sequence=row["sequence"],
                type=row["type"],
                node=row["node"],
                duration_ms=row["duration_ms"],
                payload=_event_payload(json.loads(row["payload_json"])),
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in rows
        ]

    async def interrupt_active(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """UPDATE runs SET status = ?, error = ?, updated_at = ?
                   WHERE status IN (?, ?)""",
                (
                    RunStatus.INTERRUPTED.value,
                    "The backend restarted before this run finished.",
                    utcnow().isoformat(),
                    RunStatus.QUEUED.value,
                    RunStatus.RUNNING.value,
                ),
            )
            await db.commit()
            return cursor.rowcount

    async def cleanup(self, retention_days: int) -> int:
        cutoff = (utcnow() - timedelta(days=retention_days)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            cursor = await db.execute("DELETE FROM runs WHERE updated_at < ?", (cutoff,))
            await db.commit()
            return cursor.rowcount

    async def delete_run(self, run_id: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT status FROM runs WHERE id = ?", (run_id,))
            row = await cursor.fetchone()
            if row is None:
                return False
            if RunStatus(row["status"]) not in TERMINAL_STATUSES:
                raise RuntimeError("active")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            await db.commit()
            return True

    @staticmethod
    def _summary(row: aiosqlite.Row) -> RunSummary:
        return RunSummary(
            id=row["id"], question=row["question"], status=RunStatus(row["status"]),
            current_node=row["current_node"], error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @classmethod
    def _snapshot(cls, row: aiosqlite.Row) -> RunSnapshot:
        summary = cls._summary(row)
        answer = AnswerPayload.model_validate_json(row["answer_json"]) if row["answer_json"] else None
        return RunSnapshot(**summary.model_dump(), answer=answer, last_sequence=row["last_sequence"])
