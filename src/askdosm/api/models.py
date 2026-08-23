"""Public, JSON-safe API contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from askdosm.models import AnswerPayload


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


TERMINAL_STATUSES = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.INTERRUPTED}


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=1, max_length=500)
    conversation_id: str | None = None


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    sequence: int
    type: str
    timestamp: datetime
    node: str | None = None
    duration_ms: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    conversation_id: str
    question: str
    resolved_question: str | None = None
    status: RunStatus
    current_node: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class RunSnapshot(RunSummary):
    answer: AnswerPayload | None = None
    last_sequence: int = 0


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    latest_status: RunStatus


class ConversationSnapshot(ConversationSummary):
    turns: list[RunSnapshot]


class HealthStatus(BaseModel):
    status: str
    database: str
    catalogue: str
    llm: str
    embeddings: str
