"""Node implementations, kept independent for unit testing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from askdosm.agent.prompts import INTENT_SYSTEM, PLAN_SYSTEM
from askdosm.agent.state import AgentState
from askdosm.analysis import analyze
from askdosm.catalogue import Catalogue, Embedder
from askdosm.data import DatasetCache, execute_plan, resolve_latest
from askdosm.followups import generate_follow_ups
from askdosm.models import (
    AnswerPayload,
    ExecutionTrace,
    Operation,
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
    intent = _normalize_intent(state["question"], intent)
    return {"intent": intent, "retry_count": state.get("retry_count", 0), "errors": []}


def _normalize_intent(question: str, intent: QuestionIntent) -> QuestionIntent:
    """Repair obvious omissions deterministically without inventing statistical facts."""
    text = question.casefold()
    updates: dict[str, Any] = {}

    if intent.domain and "/" in intent.domain:
        updates["domain"] = intent.domain.split("/", 1)[0]

    years = re.findall(r"\b(?:19|20)\d{2}\b", text)
    if years:
        updates["start_period"] = intent.start_period or years[0]
        updates["end_period"] = intent.end_period or years[-1]
    if any(term in text for term in ["latest", "current", "terkini", "semasa"]):
        updates["latest"] = True
    if intent.entities and not intent.geography_level:
        updates["geography_level"] = "state"
    elif not intent.geography_level and "malaysia" in text:
        updates["geography_level"] = "national"

    repaired = intent.model_copy(update=updates)
    has_period = bool(repaired.start_period or repaired.end_period or repaired.latest)
    if repaired.metric and repaired.geography_level and has_period:
        repaired = repaired.model_copy(update={"ambiguous": False, "clarification": None})
    return repaired


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
    filters = []
    for item in plan.filters:
        if item.column == "date" and isinstance(item.value, str):
            raw = item.value.casefold()
            if raw in {"latest", "current", "most recent", "latest-01-01", "latest_quarter_date"}:
                continue
        filters.append(item)
    plan = plan.model_copy(update={"filters": filters})
    return {"query_plan": plan}


def execute_query(state: AgentState, services: NodeServices) -> dict:
    frame = execute_plan(state["source_frame"], state["selected_dataset"], state["query_plan"])
    if state["intent"].latest:
        frame = resolve_latest(frame)
    return {"query_frame": frame}


def analyze_result(state: AgentState, services: NodeServices) -> dict:
    result = analyze(state["query_frame"], state["selected_dataset"], state["query_plan"])
    return {"analysis_result": result}


def _detect_date_range_gap(state: AgentState) -> str | None:
    """If the query returned no rows because the requested date is outside the
    dataset's coverage, return a helpful message; otherwise return None."""
    frame = state.get("source_frame")
    plan = state.get("query_plan")
    if frame is None or plan is None or "date" not in frame.columns or frame.empty:
        return None
    actual_min = pd.Timestamp(frame["date"].min())
    actual_max = pd.Timestamp(frame["date"].max())
    requested_periods: list[str] = []
    for spec in plan.filters:
        if spec.column != "date":
            continue
        if spec.operator == "eq" and isinstance(spec.value, str):
            requested_periods.append(spec.value)
        elif spec.operator in {"gte", "lte"} and isinstance(spec.value, str):
            requested_periods.append(spec.value)
        elif spec.operator == "between" and isinstance(spec.value, list):
            requested_periods.extend(str(v) for v in spec.value)
    if not requested_periods:
        return None
    requested = pd.Timestamp(min(requested_periods))
    if requested > actual_max:
        coverage = actual_max.strftime("%Y")
        latest_year = actual_max.strftime("%Y")
        return (
            f"The {state['selected_dataset'].title} dataset covers data up to {latest_year}, "
            f"but you asked for {requested.strftime('%Y')}. "
            f"No data is available for that period yet."
        )
    return None


def validate_result_node(state: AgentState, services: NodeServices) -> dict:
    validation = validate_result(state["analysis_result"], state["selected_dataset"], state["query_plan"])
    retry_count = state.get("retry_count", 0)
    updates: dict[str, Any] = {"validation": validation}
    if not validation.valid:
        if state["analysis_result"].row_count == 0:
            gap_message = _detect_date_range_gap(state)
            if gap_message is not None:
                updates.update({
                    "errors": [gap_message],
                    "validation": validation.model_copy(update={
                        "status": "unsupported",
                        "errors": [gap_message],
                        "retry_action": "graceful_failure",
                    }),
                    "final_status": "unsupported",
                })
                return updates
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


def _format_value(value: float | int | str | None, unit: str, language: str = "en") -> str:
    if isinstance(value, float):
        rendered = f"{value:,.2f}".rstrip("0").rstrip(".")
    else:
        rendered = str(value)
    localized_unit = {"percent": "peratus", "thousand people": "ribu orang"}.get(unit, unit) if language == "ms" else unit
    return f"{rendered} {localized_unit}".strip()


def generate_response(state: AgentState, services: NodeServices) -> dict:
    result = state["analysis_result"]
    definition = state["selected_dataset"]
    language = state["intent"].language.value
    metric_display = {
        "population": "populasi", "u_rate": "kadar pengangguran", "lf_unemployed": "bilangan penganggur",
        "p_rate": "kadar penyertaan", "lf": "tenaga buruh", "inflation_yoy": "kadar inflasi",
    }.get(result.metric, result.metric) if language == "ms" else result.metric
    labels_ms = {
        "start": "nilai awal", "end": "nilai akhir", "difference": "perbezaan",
        "percentage_growth": "pertumbuhan peratus", "cagr": "CAGR",
        "mean": "purata", "median": "median", "minimum": "minimum", "maximum": "maksimum",
        "sum": "jumlah", "count": "bilangan",
    }
    operation = state["query_plan"].operation
    extreme_key = "minimum" if operation == Operation.MIN else "maximum" if operation == Operation.MAX else None
    extreme_value = result.supporting_values.get(extreme_key) if extreme_key else None
    extreme_row = None
    if extreme_value is not None:
        extreme_row = next(
            (
                row for row in result.rows
                if row.get(result.metric) is not None
                and float(row[result.metric]) == float(extreme_value)
            ),
            None,
        )
    entity_columns = [
        column for column in definition.dimensions
        if column != "date" and column not in definition.default_filters
    ]
    entity_column = next(
        (column for column in entity_columns if extreme_row and extreme_row.get(column) is not None),
        None,
    )
    if extreme_row and entity_column:
        entity = str(extreme_row[entity_column])
        rendered_value = _format_value(extreme_value, result.unit, language)
        if language == "ms":
            direction = "paling sedikit" if operation == Operation.MIN else "paling banyak"
            subject = "Negeri atau wilayah" if entity_column == "state" else entity_column.replace("_", " ").capitalize()
            answer_text = f"{subject} dengan {metric_display} {direction} ialah {entity}, dengan {rendered_value}."
        else:
            direction = "lowest" if operation == Operation.MIN else "highest"
            subject = "state or federal territory" if entity_column == "state" else entity_column.replace("_", " ")
            answer_text = f"The {subject} with the {direction} {result.metric} is {entity}, at {rendered_value}."
    elif result.supporting_values:
        facts = ", ".join(
            f"{labels_ms.get(key, key.replace('_', ' ')) if language == 'ms' else key.replace('_', ' ')}: "
            f"{_format_value(value, 'percent' if key in {'percentage_growth', 'cagr'} else result.unit, language)}"
            for key, value in result.supporting_values.items()
        )
        answer_text = f"Berdasarkan data DOSM yang dipilih, {facts}." if language == "ms" else f"Based on the selected DOSM data, {facts}."
    elif result.rows:
        first = result.rows[0]
        answer_text = (
            f"Nilai {metric_display} yang diminta ialah {_format_value(first.get(result.metric), result.unit, language)}."
            if language == "ms"
            else f"The requested {result.metric} is {_format_value(first.get(result.metric), result.unit)}."
        )
        if result.row_count > 1:
            answer_text = (
                f"Saya menemui {result.row_count} pemerhatian yang sepadan untuk {metric_display}. Lihat jadual atau carta di bawah."
                if language == "ms"
                else f"I found {result.row_count} matching observations for {result.metric}. See the table or chart below."
            )
    else:
        answer_text = "Tiada pemerhatian yang sepadan ditemui." if language == "ms" else "No matching observations were found."
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
    follow_ups = generate_follow_ups(
        dataset=definition, intent=state["intent"], plan=state["query_plan"], result=result,
    )
    payload = AnswerPayload(
        answer=answer_text,
        table_rows=result.rows,
        visualization=state["visualization"],
        source=source,
        trace=trace,
        follow_ups=follow_ups,
    )
    return {"answer": payload, "final_status": "complete"}


def graceful_failure(state: AgentState, services: NodeServices) -> dict:
    message = " ".join(state.get("errors", [])) or "The question could not be answered from the supported datasets."
    payload = AnswerPayload(
        answer=message,
        error=message,
        trace=ExecutionTrace(intent=state.get("intent"), retry_count=state.get("retry_count", 0), validation=state.get("validation")),
    )
    return {"answer": payload, "final_status": "failed"}
