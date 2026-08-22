import asyncio
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from askdosm.api.app import create_app
from askdosm.api.models import RunStatus
from askdosm.api.store import RunStore
from askdosm.config import Settings
from askdosm.models import AnswerPayload


class FakeService:
    def ask(self, question, *, event_sink=None):
        assert question
        if event_sink:
            event_sink({"type": "node.started", "node": "parse_question", "payload": {}})
            event_sink({"type": "intent", "node": "parse_question", "payload": {"language": "en"}})
            event_sink({"type": "candidates", "node": "search_catalogue", "payload": [{"dataset_id": "population_malaysia"}]})
            event_sink({"type": "node.completed", "node": "parse_question", "duration_ms": 1.5, "payload": {}})
        return AnswerPayload(answer="A validated answer")


def api_settings(tmp_path: Path) -> Settings:
    return Settings(
        run_db_path=tmp_path / "runs.sqlite3",
        cache_dir=tmp_path / "cache",
        catalogue_path=Path("data/catalogue.json"),
    )


def test_run_api_persists_events_and_answer(tmp_path):
    app = create_app(api_settings(tmp_path), service_factory=FakeService)
    with TestClient(app) as client:
        created = client.post("/api/runs", json={"question": "Latest population?"})
        assert created.status_code == 202
        run_id = created.json()["id"]
        for _ in range(100):
            snapshot = client.get(f"/api/runs/{run_id}").json()
            if snapshot["status"] == "completed":
                break
            asyncio.run(asyncio.sleep(0.01))
        assert snapshot["answer"]["answer"] == "A validated answer"
        stream = client.get(f"/api/runs/{run_id}/events")
        assert "event: intent" in stream.text
        assert '"items":[{"dataset_id":"population_malaysia"}]' in stream.text
        assert "event: run.completed" in stream.text
        assert client.delete(f"/api/runs/{run_id}").status_code == 204


def test_api_validates_question(tmp_path):
    app = create_app(api_settings(tmp_path), service_factory=FakeService)
    with TestClient(app) as client:
        assert client.post("/api/runs", json={"question": ""}).status_code == 422
        assert client.get("/api/runs/missing").status_code == 404


@pytest.mark.asyncio
async def test_store_interrupts_active_runs_and_replays_in_order(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite3")
    await store.initialize()
    await store.create_run("one", "Question")
    await store.update_status("one", RunStatus.RUNNING)
    first = await store.append_event("one", {"type": "run.started", "payload": {}})
    second = await store.append_event("one", {"type": "intent", "payload": {"safe": True}})
    assert [event.sequence for event in await store.get_events("one", first.sequence)] == [second.sequence]
    assert await store.interrupt_active() == 1
    assert (await store.get_run("one")).status == RunStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_store_replays_legacy_list_payload_as_an_object(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite3")
    await store.initialize()
    await store.create_run("legacy", "Question")
    async with aiosqlite.connect(store.path) as db:
        await db.execute(
            """INSERT INTO run_events
               (run_id, sequence, type, payload_json, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            ("legacy", 1, "candidates", '[{"dataset_id":"population_malaysia"}]', "2026-01-01T00:00:00+00:00"),
        )
        await db.commit()

    events = await store.get_events("legacy")

    assert events[0].payload == {"items": [{"dataset_id": "population_malaysia"}]}
