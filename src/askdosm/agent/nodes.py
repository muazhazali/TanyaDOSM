"""Node implementations, kept independent for unit testing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from askdosm.agent.prompts import INTENT_SYSTEM, PLAN_SYSTEM
from askdosm.agent.state import AgentState
from askdosm.analysis import analyze
from askdosm.catalogue import Catalogue, Embedder
from askdosm.data import DatasetCache, execute_plan, resolve_latest
from askdosm.models import (
    AnswerPayload,
    ExecutionTrace,
    OutputKind,
    QueryPlan,
    QuestionIntent,
    SourceReference,
)
from askdosm.validation import validate_result
from askdosm.visualization import choose_visualization


class StructuredModel(Protocol):
    def with_structured_output(self, schema: type): ...


@dataclass
class NodeServices:
    catalogue: Catalogue
    cache: DatasetCache
    llm: StructuredModel
    embedder: Embedder | None
    embedding_cache_dir: Any
    max_retries: int = 2


def parse_question(state: AgentState, services: NodeServices) -> dict:
    parser = services.llm.with_structured_output(QuestionIntent)
    intent = parser.invoke([("system", INTENT_SYSTEM), ("human", state["question"])])
    return {"intent": intent, "retry_count": state.get("retry_count", 0), "errors": []}


def search_catalogue(state: AgentState, services: NodeServices) -> dict:
    intent = state["intent"]
    candidates = services.catalogue.search_hybrid(
        state["question"], intent, services.embedder, services.embedding_cache_dir
    )
    return {"candidates": candidates}


def select_dataset(state: AgentState, services: NodeServices) -> dict:
    intent = state["intent"]
    if intent.multi_dataset:
        return {"final_status": "unsupported", "errors": ["This version supports one dataset per question."]}
    if intent.ambiguous:
        return {"final_status": "clarification", "errors": [intent.clarification or "Please clarify the metric, geography, or period."]}
    candidates = state.get("candidates", [])
    if not candidates or candidates[0].score < 0.15:
        return {"final_status": "unsupported", "errors": ["No supported dataset confidently matches this question."]}
    if len(candidates) > 1 and candidates[0].score - candidates[1].score < 0.015:
        return {"final_status": "clarification", "errors": ["The question matches multiple datasets. Please specify national or state-level data."]}
    selected = services.catalogue.get(candidates[0].dataset_id)
    return {"selected_dataset": selected, "selection_reason": candidates[0].reason, "final_status": "selected"}


def inspect_schema(state: AgentState, services: NodeServices) -> dict:
    definition = state["selected_dataset"]
    frame = services.cache.load(definition)
    return {
        "source_frame": frame,
        "cache_freshness": services.cache.freshness(definition.dataset_id),
        "metadata": {
            "columns": list(frame.columns),
            "dimensions": definition.dimensions,
            "measures": [item.model_dump() for item in definition.measures],
            "default_filters": definition.default_filters,
            "frequency": definition.frequency,
        },
    }


def build_query_plan(state: AgentState, services: NodeServices) -> dict:
    definition = state["selected_dataset"]
    planner = services.llm.with_structured_output(QueryPlan)
    context = {
        "question": state["question"],
        "intent": state["intent"].model_dump(mode="json"),
        "dataset_id": definition.dataset_id,
        "dimensions": definition.dimensions,
        "measures": [item.model_dump() for item in definition.measures],
        "default_filters": definition.default_filters,
        "frequency": definition.frequency,
        "previous_errors": state.get("errors", []),
    }
    plan = planner.invoke([("system", PLAN_SYSTEM), ("human", json.dumps(context))])
    if plan.dataset_id != definition.dataset_id:
        raise ValueError("Planner returned an unregistered or different dataset ID")
    return {"query_plan": plan}


def execute_query(state: AgentState, services: NodeServices) -> dict:
    frame = execute_plan(state["source_frame"], state["selected_dataset"], state["query_plan"])
    if state["intent"].latest:
        frame = resolve_latest(frame)
    return {"query_frame": frame}


def analyze_result(state: AgentState, services: NodeServices) -> dict:
    result = analyze(state["query_frame"], state["selected_dataset"], state["query_plan"])
    return {"analysis_result": result}


def validate_result_node(state: AgentState, services: NodeServices) -> dict:
    validation = validate_result(state["analysis_result"], state["selected_dataset"], state["query_plan"])
    retry_count = state.get("retry_count", 0)
    updates: dict[str, Any] = {"validation": validation}
    if not validation.valid:
        retry_count += 1
        updates.update({"retry_count": retry_count, "errors": validation.errors})
        if retry_count >= services.max_retries:
            updates["final_status"] = "unsupported"
    return updates


def generate_visualization(state: AgentState, services: NodeServices) -> dict:
    requested = state["intent"].requested_output
    spec = choose_visualization(state["analysis_result"], state["query_plan"])
    if requested is not None and requested != OutputKind.NONE and state["analysis_result"].row_count > 1:
        spec.kind = requested
    return {"visualization": spec}


def _format_value(value: float | int | str | None, unit: str) -> str:
    if isinstance(value, float):
        rendered = f"{value:,.2f}".rstrip("0").rstrip(".")
    else:
        rendered = str(value)
    return f"{rendered} {unit}".strip()


def generate_response(state: AgentState, services: NodeServices) -> dict:
    result = state["analysis_result"]
    definition = state["selected_dataset"]
    if result.supporting_values:
        facts = ", ".join(
            f"{key.replace('_', ' ')}: {_format_value(value, 'percent' if key in {'percentage_growth', 'cagr'} else result.unit)}"
            for key, value in result.supporting_values.items()
        )
        answer_text = f"Based on the selected DOSM data, {facts}."
    elif result.rows:
        first = result.rows[0]
        answer_text = f"The requested {result.metric} is {_format_value(first.get(result.metric), result.unit)}."
        if result.row_count > 1:
            answer_text = f"I found {result.row_count} matching observations for {result.metric}. See the table or chart below."
    else:
        answer_text = "No matching observations were found."
    periods = [str(row.get("date")) for row in result.rows if row.get("date")]
    period = f"{min(periods)} to {max(periods)}" if periods else None
    source = SourceReference(
        dataset_id=definition.dataset_id,
        title=definition.title,
        agency=definition.source_agency,
        url=definition.source_url,
        period=period,
        unit=result.unit,
        cache_freshness=state.get("cache_freshness"),
    )
    trace = ExecutionTrace(
        intent=state["intent"], selection_reason=state.get("selection_reason"), query_plan=state["query_plan"],
        calculation=result.calculation, rows_used=result.row_count, validation=state["validation"], retry_count=state.get("retry_count", 0)
    )
    payload = AnswerPayload(
        answer=answer_text, table_rows=result.rows, visualization=state["visualization"], source=source, trace=trace
    )
    return {"answer": payload, "final_status": "complete"}


def graceful_failure(state: AgentState, services: NodeServices) -> dict:
    message = " ".join(state.get("errors", [])) or "The question could not be answered from the five supported datasets."
    payload = AnswerPayload(
        answer=message,
        error=message,
        trace=ExecutionTrace(intent=state.get("intent"), retry_count=state.get("retry_count", 0), validation=state.get("validation")),
    )
    return {"answer": payload, "final_status": "failed"}
