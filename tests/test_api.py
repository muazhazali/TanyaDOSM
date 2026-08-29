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
from askdosm.providers import HostedProviderError


class FakeService:
    resolved = []

    def resolve_question(self, question, history):
        assert history[-1]["assistant"] == "A validated answer"
        resolved = f"Resolved: {question}"
        self.resolved.append(resolved)
        return resolved

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


def test_follow_up_reuses_conversation_and_persists_resolved_question(tmp_path):
    FakeService.resolved.clear()
    app = create_app(api_settings(tmp_path), service_factory=FakeService)
    with TestClient(app) as client:
        first = client.post("/api/runs", json={"question": "Population in Johor in 2025?"}).json()
        for _ in range(100):
            if client.get(f"/api/runs/{first['id']}").json()["status"] == "completed":
                break
            asyncio.run(asyncio.sleep(0.01))
        second = client.post(
            "/api/runs",
            json={"question": "What about Selangor?", "conversation_id": first["conversation_id"]},
        ).json()
        for _ in range(100):
            snapshot = client.get(f"/api/runs/{second['id']}").json()
            if snapshot["status"] == "completed":
                break
            asyncio.run(asyncio.sleep(0.01))
        conversation = client.get(f"/api/conversations/{first['conversation_id']}").json()

    assert conversation["turn_count"] == 2
    assert [turn["question"] for turn in conversation["turns"]] == [
        "Population in Johor in 2025?", "What about Selangor?",
    ]
    assert snapshot["resolved_question"] == "Resolved: What about Selangor?"
    assert FakeService.resolved == ["Resolved: What about Selangor?"]


def test_follow_up_rejects_unknown_conversation(tmp_path):
    app = create_app(api_settings(tmp_path), service_factory=FakeService)
    with TestClient(app) as client:
        response = client.post(
            "/api/runs", json={"question": "What about Selangor?", "conversation_id": "missing"}
        )
    assert response.status_code == 404


def test_health_reports_hosted_providers(tmp_path, monkeypatch):
    monkeypatch.setattr("askdosm.api.app.check_groq", lambda settings: "ready")
    monkeypatch.setattr("askdosm.api.app.check_cloudflare", lambda settings: "unavailable")
    app = create_app(api_settings(tmp_path), service_factory=FakeService)

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.json() == {
        "status": "ready",
        "database": "ready",
        "catalogue": "ready",
        "llm": "ready",
        "embeddings": "unavailable",
    }


def test_conversation_management_and_feedback(tmp_path):
    app = create_app(api_settings(tmp_path), service_factory=FakeService)
    with TestClient(app) as client:
        created = client.post("/api/runs", json={"question": "Latest population?"}).json()
        for _ in range(100):
            snapshot = client.get(f"/api/runs/{created['id']}").json()
            if snapshot["status"] == "completed":
                break
            asyncio.run(asyncio.sleep(0.01))

        renamed = client.patch(
            f"/api/conversations/{created['conversation_id']}", json={"title": "Population notes"}
        )
        feedback = client.post(
            f"/api/runs/{created['id']}/feedback", json={"helpful": True}
        )
        deleted = client.delete(f"/api/conversations/{created['conversation_id']}")

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Population notes"
    assert feedback.status_code == 204
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_manager_cancels_a_queued_run(tmp_path):
    from askdosm.api.manager import RunManager

    store = RunStore(tmp_path / "runs.sqlite3")
    await store.initialize()
    manager = RunManager(store, FakeService)
    snapshot = await manager.create("Latest population?")

    assert manager.queue_position(snapshot.id) == 1
    assert await manager.cancel(snapshot.id) is True
    cancelled = await store.get_run(snapshot.id)
    assert cancelled is not None
    assert cancelled.status == RunStatus.INTERRUPTED


def test_default_app_rejects_missing_groq_key_at_startup(tmp_path):
    settings = api_settings(tmp_path).model_copy(update={"groq_api_key": ""})
    app = create_app(settings)

    with pytest.raises(RuntimeError, match="ASKDOSM_GROQ_API_KEY"):
        with TestClient(app):
            pass


def test_safe_provider_error_is_returned_to_run(tmp_path):
    class FailingService:
        def ask(self, question, *, event_sink=None):
            raise HostedProviderError("Hosted language model free-tier quota is temporarily unavailable.")

    app = create_app(api_settings(tmp_path), service_factory=FailingService)
    with TestClient(app) as client:
        created = client.post("/api/runs", json={"question": "Latest population?"}).json()
        for _ in range(100):
            snapshot = client.get(f"/api/runs/{created['id']}").json()
            if snapshot["status"] == "failed":
                break
            asyncio.run(asyncio.sleep(0.01))

    assert snapshot["error"] == "Hosted language model free-tier quota is temporarily unavailable."


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


@pytest.mark.asyncio
async def test_store_migrates_independent_runs_to_one_turn_conversations(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    async with aiosqlite.connect(path) as db:
        await db.executescript(
            """CREATE TABLE runs (
                id TEXT PRIMARY KEY, question TEXT NOT NULL, status TEXT NOT NULL,
                current_node TEXT, answer_json TEXT, error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE run_events (
                run_id TEXT NOT NULL, sequence INTEGER NOT NULL, type TEXT NOT NULL,
                node TEXT, duration_ms REAL, payload_json TEXT NOT NULL, timestamp TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence)
            );"""
        )
        await db.execute(
            "INSERT INTO runs (id, question, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("old", "Legacy question", "completed", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        await db.commit()

    store = RunStore(path)
    await store.initialize()
    conversation = await store.get_conversation("old")

    assert conversation is not None
    assert conversation.title == "Legacy question"
    assert conversation.turns[0].conversation_id == "old"
