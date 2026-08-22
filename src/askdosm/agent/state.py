"""LangGraph state definition."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

import pandas as pd

from askdosm.models import (
    AnalysisResult,
    AnswerPayload,
    DatasetCandidate,
    DatasetDefinition,
    QuestionIntent,
    QueryPlan,
    ValidationResult,
    VisualizationSpec,
)


class AgentState(TypedDict, total=False):
    question: str
    intent: QuestionIntent
    candidates: list[DatasetCandidate]
    selected_dataset: DatasetDefinition
    selection_reason: str
    source_frame: pd.DataFrame
    query_plan: QueryPlan
    query_frame: pd.DataFrame
    analysis_result: AnalysisResult
    validation: ValidationResult
    visualization: VisualizationSpec
    answer: AnswerPayload
    retry_count: int
    errors: list[str]
    cache_freshness: str | None
    final_status: str
    metadata: dict[str, Any]
    event_sink: Callable[[dict[str, Any]], None]
