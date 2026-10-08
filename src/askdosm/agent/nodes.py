"""Node implementations, kept independent for unit testing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from askdosm.agent.prompts import INTENT_SYSTEM, MULTI_PLAN_SYSTEM, PLAN_SYSTEM
from askdosm.agent.state import AgentState
from askdosm.analysis import analyze, _records as combined_records
from askdosm.catalogue import Catalogue, Embedder, JoinRegistry
from askdosm.combine import CombineError, combine
from askdosm.data import DatasetCache, execute_plan, resolve_latest
from askdosm.followups import generate_follow_ups
from askdosm.models import (
    AnalysisResult,
    AnswerPayload,
    CombineHow,
    CombineSpec,
    ExecutionTrace,
    IntentKind,
    MultiPlan,
    Operation,
    OutputKind,
    PlanStep,
    QueryPlan,
    QuestionIntent,
    SourceReference,
    StepKind,
    TokenUsage,
)
from askdosm.validation import validate_result
from askdosm.visualization import choose_visualization


class StructuredModel(Protocol):
    def with_structured_output(self, schema: type): ...
    @property
    def usage(self) -> TokenUsage | None: ...


@dataclass
class NodeServices:
    catalogue: Catalogue
    cache: DatasetCache
    llm: StructuredModel
    embedder: Embedder | None
    embedding_cache_dir: Any
    max_retries: int = 2
    min_match_score: float = 0.10
    clarification_gap: float = 0.03
    assistant_facts_path: Any = None
    joins: JoinRegistry | None = None
    enable_multi_dataset: bool = True
    max_plan_steps: int = 3
    max_join_rows: int = 50_000


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


_DOMAIN_LABELS_MS = {
    "demography": "kependudukan", "labour": "buruh", "prices": "harga",
    "national accounts": "akaun negara", "households": "isi rumah",
}


def answer_capability(state: AgentState, services: NodeServices) -> dict:
    """Describe what the assistant can answer, using only catalogue metadata."""
    language = state["intent"].language.value if state.get("intent") else "en"
    datasets = services.catalogue.all()
    domains: dict[str, int] = {}
    for definition in datasets:
        domains[definition.domain] = domains.get(definition.domain, 0) + 1

    examples = [
        definition.title
        for definition in datasets
        if definition.geography_level == "national"
    ][:5]
    if not examples:
        examples = [definition.title for definition in datasets[:5]]

    if language == "ms":
        domain_text = ", ".join(
            f"{_DOMAIN_LABELS_MS.get(domain, domain)} ({count})"
            for domain, count in sorted(domains.items())
        )
        answer_text = (
            f"Saya boleh menjawab soalan tentang statistik rasmi Malaysia daripada {len(datasets)} set data "
            f"merentas domain berikut: {domain_text}. "
            "Tanya satu ukuran, satu tempat, dan satu tempoh — contohnya, "
            f'"{examples[0]}" jika anda mahukan angka terkini.'
        )
    else:
        domain_text = ", ".join(f"{domain} ({count})" for domain, count in sorted(domains.items()))
        answer_text = (
            f"I can answer questions about official Malaysian statistics from {len(datasets)} "
            f"curated datasets across these domains: {domain_text}. "
            "Ask about one measure, one place, and one time period — for example, "
            f'"{examples[0]}" for the latest figure.'
        )

    payload = AnswerPayload(
        answer=answer_text,
        follow_ups=[
            "What is Malaysia's latest population?",
            "Show unemployment trends in Johor since 2020.",
        ],
        trace=ExecutionTrace(intent=state.get("intent"), token_usage=getattr(services.llm, "usage", None)),
    )
    return {"answer": payload, "final_status": "capability"}


def _load_assistant_facts(services: NodeServices) -> list[dict[str, Any]]:
    path = services.assistant_facts_path
    if path is None:
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return raw.get("facts", []) if isinstance(raw, dict) else []
    except (OSError, ValueError):
        return []


def _match_fact(question: str, facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the curated fact whose alias best matches the question.

    Matching is deterministic and purely lexical: the curated text is what gets
    shown, so the model never free-generates project facts.
    """
    text = f" {re.sub(r'[^\w\s]', ' ', question.casefold())} "
    words = set(text.split())
    best: dict[str, Any] | None = None
    best_score = 0
    for fact in facts:
        score = 0
        for alias in fact.get("aliases", []):
            alias_cf = alias.casefold().strip()
            if not alias_cf:
                continue
            if alias_cf in text:
                # Longer phrases are stronger evidence than single words.
                score = max(score, len(alias_cf.split()) * 2 + 1)
            elif len(alias_cf.split()) == 1 and alias_cf in words:
                score = max(score, 1)
        if score > best_score:
            best_score = score
            best = fact
    return best


def answer_project(state: AgentState, services: NodeServices) -> dict:
    """Answer questions about the assistant/project from curated facts only."""
    intent = state.get("intent")
    language = intent.language.value if intent else "en"
    facts = _load_assistant_facts(services)
    fact = _match_fact(state["question"], facts)
    if fact is None:
        # No curated fact matches: fall back to the catalogue-grounded capability answer.
        return answer_capability(state, services)
    answer_text = fact.get("answer_ms" if language == "ms" else "answer_en") or fact.get("answer_en", "")
    payload = AnswerPayload(
        answer=answer_text,
        follow_ups=[
            "What is Malaysia's latest population?",
            "What data do you have?",
        ],
        trace=ExecutionTrace(intent=intent, token_usage=getattr(services.llm, "usage", None)),
    )
    return {"answer": payload, "final_status": "project"}


def _infer_assumptions(intent: QuestionIntent, definition: Any) -> list[str]:
    """Note any geography or period we supplied by default so the answer is honest."""
    notes: list[str] = []
    if not intent.geography_level:
        if definition.geography_level == "national":
            notes.append("Assumed national-level data because no place was specified.")
        else:
            notes.append(f"Assumed {definition.geography_level}-level data because no place was specified.")
    if not (intent.start_period or intent.end_period or intent.latest):
        notes.append("Used the latest available period because no time period was specified.")
    return notes


def select_dataset(state: AgentState, services: NodeServices) -> dict:
    intent = state["intent"]
    if intent.multi_dataset and not services.enable_multi_dataset:
        return {"final_status": "unsupported", "errors": ["This version supports one dataset per question."]}
    candidates = state.get("candidates", [])
    floor = services.min_match_score
    if not candidates or candidates[0].score < floor:
        # Nothing in the catalogue plausibly matches the topic: ask for one that does.
        if intent.clarification:
            return {"final_status": "clarification", "errors": [intent.clarification]}
        return {"final_status": "unsupported", "errors": ["No supported dataset confidently matches this question."]}
    # A clear leader on the same topic proceeds even if the model flagged ambiguity,
    # because the deterministic ranking already resolved it (stopwords removed, ties
    # broken by the requested geography). Only a near-tie between *different topics*
    # with no geography given invites a question; same-topic ties default to national.
    gap = services.clarification_gap
    if len(candidates) > 1 and candidates[0].score - candidates[1].score < gap:
        leader = services.catalogue.get(candidates[0].dataset_id)
        runner = services.catalogue.get(candidates[1].dataset_id)
        if leader.domain != runner.domain and not intent.geography_level:
            return {"final_status": "clarification", "errors": [intent.clarification or "The question matches multiple datasets. Please specify national or state-level data."]}
    selected = services.catalogue.get(candidates[0].dataset_id)
    assumptions = _infer_assumptions(intent, selected)
    return {
        "selected_dataset": selected,
        "selection_reason": candidates[0].reason,
        "assumptions": assumptions,
        "final_status": "selected",
    }


def plan_multi(state: AgentState, services: NodeServices) -> dict:
    """Ask the LLM for a declarative DAG of dataset operations.

    The plan is a list of fetch/combine steps, never code. It is validated by
    validate_multi before anything is executed.
    """
    planner = services.llm.with_structured_output(MultiPlan)
    catalogue_context = [
        {
            "dataset_id": item.dataset_id,
            "title": item.title,
            "domain": item.domain,
            "geography_level": item.geography_level,
            "frequency": item.frequency,
            "dimensions": item.dimensions,
            "measures": [{"name": m.name, "unit": m.unit, "aliases": m.aliases} for m in item.measures],
            "default_filters": item.default_filters,
        }
        for item in services.catalogue.all()
    ]
    joinable = services.joins._pairs if services.joins else []
    context = {
        "question": state["question"],
        "intent": state["intent"].model_dump(mode="json"),
        "max_steps": services.max_plan_steps,
        "catalogue": catalogue_context,
        "joinable_pairs": joinable,
    }
    try:
        plan = planner.invoke([("system", MULTI_PLAN_SYSTEM), ("human", json.dumps(context))])
    except Exception as exc:
        return {
            "final_status": "unsupported",
            "errors": [f"The multi-dataset request could not be planned ({type(exc).__name__})."],
        }
    return {"multi_plan": plan, "errors": []}


def _resolve_source_dataset(
    step_id: str, steps_by_id: dict[str, PlanStep], fetch_ids: dict[str, str]
) -> str | None:
    step = steps_by_id.get(step_id)
    if step is None:
        return None
    if step.kind == StepKind.FETCH:
        return fetch_ids.get(step_id)
    return None


def _validate_dag(plan: MultiPlan) -> list[str]:
    errors: list[str] = []
    step_ids = [step.step_id for step in plan.steps]
    if len(step_ids) != len(set(step_ids)):
        errors.append("The plan contains duplicate step ids.")
    known: set[str] = set()
    for step in plan.steps:
        if step.kind == StepKind.FETCH:
            if not step.dataset_id or step.plan is None:
                errors.append(f"Fetch step {step.step_id} is missing a dataset or query plan.")
        elif step.kind == StepKind.COMBINE:
            if step.combine is None:
                errors.append(f"Combine step {step.step_id} is missing its combine specification.")
            else:
                for ref in (step.combine.left, step.combine.right):
                    if ref not in known:
                        errors.append(f"Combine step {step.step_id} references unknown or later step {ref}.")
        known.add(step.step_id)
    if plan.final_step not in known:
        errors.append("The final step does not exist in the plan.")
    return errors


def validate_multi(state: AgentState, services: NodeServices) -> dict:
    """Validate the declarative DAG against the catalogue and the join whitelist."""
    plan = state.get("multi_plan")
    if plan is None:
        return {"final_status": "unsupported", "errors": ["No plan was produced."]}

    errors = _validate_dag(plan)
    if len(plan.steps) > services.max_plan_steps:
        errors.append(f"The plan uses more than the allowed {services.max_plan_steps} steps.")

    steps_by_id = {step.step_id: step for step in plan.steps}
    fetch_ids: dict[str, str] = {}
    normalized_steps: list[PlanStep] = []
    for step in plan.steps:
        if step.kind == StepKind.FETCH:
            try:
                definition = services.catalogue.get(step.dataset_id or "")
            except ValueError:
                errors.append(f"Unknown dataset for step {step.step_id}: {step.dataset_id}")
                normalized_steps.append(step)
                continue
            if step.plan is not None:
                allowed = set(definition.dimensions) | {m.name for m in definition.measures}
                referenced = set(step.plan.columns) | set(step.plan.group_by) | {f.column for f in step.plan.filters}
                invalid = sorted(referenced - allowed)
                if invalid:
                    errors.append(f"Step {step.step_id} references unknown columns: {', '.join(invalid)}")
                if step.plan.dataset_id != definition.dataset_id:
                    step = step.model_copy(
                        update={"plan": step.plan.model_copy(update={"dataset_id": definition.dataset_id})}
                    )
            fetch_ids[step.step_id] = definition.dataset_id
        normalized_steps.append(step)

    steps_by_id = {step.step_id: step for step in normalized_steps}

    for step in normalized_steps:
        if step.kind != StepKind.COMBINE or step.combine is None:
            continue
        combine = step.combine
        left_ds = _resolve_source_dataset(combine.left, steps_by_id, fetch_ids)
        right_ds = _resolve_source_dataset(combine.right, steps_by_id, fetch_ids)
        if combine.how in {CombineHow.JOIN, CombineHow.RATIO, CombineHow.DIFFERENCE}:
            if not left_ds or not right_ds:
                errors.append(f"Step {step.step_id} could not resolve its input datasets for validation.")
            elif services.joins is None or not services.joins.is_allowed(left_ds, right_ds, combine.on):
                errors.append(
                    f"Step {step.step_id} combines {left_ds} and {right_ds} on {combine.on}, "
                    "which is not a whitelisted join."
                )
        elif combine.how == CombineHow.CONCAT and not combine.on:
            errors.append(f"Step {step.step_id} concat is missing its alignment key(s).")

    if errors:
        return {"final_status": "unsupported", "errors": errors}
    return {"multi_plan": plan.model_copy(update={"steps": normalized_steps}), "final_status": "multi_validated"}


def _topological_steps(steps: list[PlanStep]) -> list[PlanStep]:
    by_id = {step.step_id: step for step in steps}
    ordered: list[PlanStep] = []
    emitted: set[str] = set()
    pending = list(steps)
    while pending:
        progressed = False
        for step in list(pending):
            deps = [step.combine.left, step.combine.right] if step.combine else []
            if all(dep in emitted for dep in deps):
                ordered.append(step)
                emitted.add(step.step_id)
                pending.remove(step)
                progressed = True
        if not progressed:
            raise ValueError("The multi-dataset plan contains a cycle.")
    return ordered


def execute_multi(state: AgentState, services: NodeServices) -> dict:
    """Execute the validated DAG: fetch each dataset, then combine deterministically."""
    plan = state["multi_plan"]
    steps = _topological_steps(plan.steps)
    by_id = {step.step_id: step for step in steps}
    frames: dict[str, Any] = {}
    results: dict[str, Any] = {}

    try:
        for step in steps:
            if step.kind == StepKind.FETCH:
                definition = services.catalogue.get(step.dataset_id or "")
                source = services.cache.load(definition)
                frame = execute_plan(source, definition, step.plan)
                if state["intent"].latest:
                    frame = resolve_latest(frame)
                frames[step.step_id] = frame
                results[step.step_id] = analyze(frame, definition, step.plan)
            elif step.kind == StepKind.COMBINE and step.combine is not None:
                left_frame = frames.get(step.combine.left)
                right_frame = frames.get(step.combine.right)
                if left_frame is None or right_frame is None:
                    raise ValueError(f"Step {step.step_id} is missing an input frame.")
                merged = combine(
                    left_frame,
                    right_frame,
                    step.combine,
                    output_metric=step.output_metric,
                    max_rows=services.max_join_rows,
                )
                frames[step.step_id] = merged
                metric = step.output_metric or (
                    merged.columns[-1] if len(merged.columns) else "value"
                )
                results[step.step_id] = AnalysisResult(
                    rows=combined_records(merged),
                    metric=metric,
                    unit="",
                    row_count=len(merged),
                    result_kind="calculated",
                    calculation=f"{step.combine.how} of {step.combine.left} and {step.combine.right}",
                )
    except (CombineError, ValueError) as exc:
        return {"final_status": "unsupported", "errors": [str(exc)]}

    final = results.get(plan.final_step)
    if final is None:
        return {"final_status": "unsupported", "errors": ["The final step produced no result."]}
    return {
        "step_frames": frames,
        "step_results": results,
        "analysis_result": final,
        "query_frame": frames.get(plan.final_step),
        "final_status": "multi_ready",
    }


def generate_multi_response(state: AgentState, services: NodeServices) -> dict:
    """Assemble a multi-source answer from the executed DAG."""
    plan = state["multi_plan"]
    final = state["analysis_result"]
    language = state["intent"].language.value

    source_definitions: list[Any] = []
    for step in plan.steps:
        if step.kind == StepKind.FETCH and step.dataset_id:
            try:
                source_definitions.append(services.catalogue.get(step.dataset_id))
            except ValueError:
                continue
    seen: set[str] = set()
    unique_definitions = []
    for definition in source_definitions:
        if definition.dataset_id not in seen:
            seen.add(definition.dataset_id)
            unique_definitions.append(definition)

    rows = final.rows or []
    if rows:
        if language == "ms":
            answer_text = (
                f"Saya menggabungkan {len(unique_definitions)} set data DOSM. "
                f"Hasilnya mengandungi {final.row_count} pemerhatian. Lihat jadual di bawah."
            )
        else:
            answer_text = (
                f"I combined {len(unique_definitions)} DOSM datasets. "
                f"The result has {final.row_count} observations. See the table below."
            )
    else:
        answer_text = (
            "Tiada pemerhatian yang sepadan ditemui." if language == "ms"
            else "No matching observations were found."
        )

    sources = [
        SourceReference(
            dataset_id=definition.dataset_id,
            title=definition.title,
            agency=definition.source_agency,
            url=definition.source_url,
            unit="",
            cache_freshness=state.get("cache_freshness"),
        )
        for definition in unique_definitions
    ]
    follow_ups = []
    if unique_definitions:
        follow_ups = generate_follow_ups(
            dataset=unique_definitions[0],
            intent=state["intent"],
            plan=_first_fetch_plan(plan),
            result=final,
        )
    payload = AnswerPayload(
        answer=answer_text,
        table_rows=final.rows,
        visualization=choose_visualization(final, _first_fetch_plan(plan)),
        source=sources[0] if sources else None,
        sources=sources,
        follow_ups=follow_ups,
        assumptions=state.get("assumptions", []),
        trace=ExecutionTrace(
            intent=state.get("intent"),
            calculation=final.calculation,
            rows_used=final.row_count,
            retry_count=state.get("retry_count", 0),
            token_usage=getattr(services.llm, "usage", None),
        ),
    )
    return {"answer": payload, "final_status": "complete"}


def _first_fetch_plan(plan: MultiPlan) -> QueryPlan:
    for step in plan.steps:
        if step.kind == StepKind.FETCH and step.plan is not None:
            return step.plan
    return QueryPlan(dataset_id="", columns=[], metric="")


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
    try:
        plan = planner.invoke([("system", PLAN_SYSTEM), ("human", json.dumps(context))])
    except Exception as exc:
        # A malformed or rejected plan should fail this question, not abort the run.
        return {
            "final_status": "unsupported",
            "errors": [f"The data request could not be prepared ({type(exc).__name__})."],
        }
    if plan.dataset_id != definition.dataset_id:
        # The planner cannot change the dataset. Try once to re-select from the
        # remaining candidates; if nothing better remains, fail gracefully instead
        # of raising and aborting the whole run.
        remaining = [
            candidate for candidate in state.get("candidates", [])
            if candidate.dataset_id != definition.dataset_id
        ]
        if remaining and state.get("reselect_count", 0) < 1:
            return {
                "candidates": remaining,
                "reselect_count": state.get("reselect_count", 0) + 1,
                "final_status": "reselect",
                "errors": ["The dataset selection was revised to better match the question."],
            }
        return {
            "final_status": "unsupported",
            "errors": ["The question could not be matched to a single supported dataset."],
        }
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
    try:
        frame = execute_plan(state["source_frame"], state["selected_dataset"], state["query_plan"])
    except Exception as exc:
        # A rejected plan (unknown column, bad filter) fails this question cleanly
        # instead of aborting the whole run.
        return {
            "final_status": "unsupported",
            "errors": [f"The data request could not be run against the selected dataset ({type(exc).__name__})."],
        }
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
        calculation=result.calculation, rows_used=result.row_count, validation=state["validation"], retry_count=state.get("retry_count", 0),
        token_usage=getattr(services.llm, "usage", None),
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
        assumptions=state.get("assumptions", []),
    )
    return {"answer": payload, "final_status": "complete"}


def graceful_failure(state: AgentState, services: NodeServices) -> dict:
    message = " ".join(state.get("errors", [])) or "The question could not be answered from the supported datasets."
    payload = AnswerPayload(
        answer=message,
        error=message,
        trace=ExecutionTrace(intent=state.get("intent"), retry_count=state.get("retry_count", 0), validation=state.get("validation"), token_usage=getattr(services.llm, "usage", None)),
    )
    return {"answer": payload, "final_status": "failed"}
