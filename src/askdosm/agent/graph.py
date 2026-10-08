"""Compiled TanyaDOSM LangGraph and public service facade."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph

from askdosm.agent import nodes
from askdosm.agent.nodes import NodeServices
from askdosm.agent.state import AgentState
from askdosm.catalogue import Catalogue, JoinRegistry
from askdosm.config import Settings, get_settings
from askdosm.data import DatasetCache
from askdosm.models import AnswerPayload, ContextResolution, IntentKind
from askdosm.agent.prompts import CONTEXT_SYSTEM
from askdosm.providers import create_chat_model, create_embedder


def _artifact_event(node_name: str, update: dict[str, Any]) -> dict[str, Any] | None:
    """Return the safe, JSON-ready part of a node update for UI inspection."""
    mapping = {
        "parse_question": ("intent", "intent"),
        "search_catalogue": ("candidates", "candidates"),
        "build_query_plan": ("query_plan", "query_plan"),
        "analyze_result": ("analysis", "analysis_result"),
        "validate_result": ("validation", "validation"),
        "generate_visualization": ("visualization", "visualization"),
        "generate_response": ("result", "answer"),
        "answer_capability": ("result", "answer"),
        "answer_project": ("result", "answer"),
        "plan_multi": ("multi_plan", "multi_plan"),
        "validate_multi": ("multi_validation", "errors"),
        "generate_multi_response": ("result", "answer"),
        "graceful_failure": ("result", "answer"),
    }
    if node_name == "select_dataset":
        selected = update.get("selected_dataset")
        return {
            "type": "selection",
            "payload": {
                "dataset_id": selected.dataset_id if selected else None,
                "title": selected.title if selected else None,
                "reason": update.get("selection_reason"),
                "status": update.get("final_status"),
                "errors": update.get("errors", []),
            },
        }
    if node_name == "inspect_schema":
        metadata = update.get("metadata", {})
        return {
            "type": "schema",
            "payload": {
                "columns": metadata.get("columns", []),
                "dimensions": metadata.get("dimensions", []),
                "measures": metadata.get("measures", []),
                "default_filters": metadata.get("default_filters", {}),
                "frequency": metadata.get("frequency"),
                "cache_freshness": update.get("cache_freshness"),
            },
        }
    if node_name == "execute_query":
        frame = update.get("query_frame")
        return {"type": "data_summary", "payload": {"rows": len(frame) if frame is not None else 0}}
    item = mapping.get(node_name)
    if not item or item[1] not in update:
        return None
    event_type, key = item
    value = update[key]
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    elif isinstance(value, list):
        payload = {
            "items": [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value]
        }
    else:
        payload = value
    return {"type": event_type, "payload": payload}


def _observed_node(
    name: str,
    function: Callable[[AgentState, NodeServices], dict[str, Any]],
    services: NodeServices,
):
    def run(state: AgentState) -> dict[str, Any]:
        sink = state.get("event_sink")
        if sink:
            sink({"type": "node.started", "node": name, "payload": {}})
        started = perf_counter()
        try:
            update = function(state, services)
        except Exception as exc:
            if sink:
                sink({
                    "type": "node.failed",
                    "node": name,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "payload": {"error": type(exc).__name__},
                })
            raise
        duration_ms = round((perf_counter() - started) * 1000, 2)
        if sink:
            sink({"type": "node.completed", "node": name, "duration_ms": duration_ms, "payload": {}})
            artifact = _artifact_event(name, update)
            if artifact:
                sink({**artifact, "node": name})
            previous_retry = state.get("retry_count", 0)
            current_retry = update.get("retry_count", previous_retry)
            if current_retry > previous_retry:
                sink({
                    "type": "retry",
                    "node": name,
                    "payload": {"attempt": current_retry, "errors": update.get("errors", [])},
                })
        return update

    return run


def build_graph(services: NodeServices):
    graph = StateGraph(AgentState)
    graph.add_node("parse_question", _observed_node("parse_question", nodes.parse_question, services))
    graph.add_node("search_catalogue", _observed_node("search_catalogue", nodes.search_catalogue, services))
    graph.add_node("answer_capability", _observed_node("answer_capability", nodes.answer_capability, services))
    graph.add_node("answer_project", _observed_node("answer_project", nodes.answer_project, services))
    graph.add_node("plan_multi", _observed_node("plan_multi", nodes.plan_multi, services))
    graph.add_node("validate_multi", _observed_node("validate_multi", nodes.validate_multi, services))
    graph.add_node("execute_multi", _observed_node("execute_multi", nodes.execute_multi, services))
    graph.add_node("generate_multi_response", _observed_node("generate_multi_response", nodes.generate_multi_response, services))
    graph.add_node("select_dataset", _observed_node("select_dataset", nodes.select_dataset, services))
    graph.add_node("inspect_schema", _observed_node("inspect_schema", nodes.inspect_schema, services))
    graph.add_node("build_query_plan", _observed_node("build_query_plan", nodes.build_query_plan, services))
    graph.add_node("execute_query", _observed_node("execute_query", nodes.execute_query, services))
    graph.add_node("analyze_result", _observed_node("analyze_result", nodes.analyze_result, services))
    graph.add_node("validate_result", _observed_node("validate_result", nodes.validate_result_node, services))
    graph.add_node("generate_visualization", _observed_node("generate_visualization", nodes.generate_visualization, services))
    graph.add_node("generate_response", _observed_node("generate_response", nodes.generate_response, services))
    graph.add_node("graceful_failure", _observed_node("graceful_failure", nodes.graceful_failure, services))

    graph.add_edge(START, "parse_question")
    graph.add_conditional_edges(
        "parse_question",
        lambda state: (
            "answer_capability" if state["intent"].kind == IntentKind.CAPABILITY
            else "answer_project" if state["intent"].kind == IntentKind.PROJECT
            else "search_catalogue"
        ),
        {
            "answer_capability": "answer_capability",
            "answer_project": "answer_project",
            "search_catalogue": "search_catalogue",
        },
    )
    graph.add_edge("search_catalogue", "select_dataset")
    graph.add_conditional_edges(
        "select_dataset",
        lambda state: (
            "plan_multi"
            if state["intent"].multi_dataset and services.enable_multi_dataset
            else "inspect_schema" if state.get("final_status") == "selected"
            else "graceful_failure"
        ),
        {
            "plan_multi": "plan_multi",
            "inspect_schema": "inspect_schema",
            "graceful_failure": "graceful_failure",
        },
    )
    graph.add_edge("plan_multi", "validate_multi")
    graph.add_conditional_edges(
        "validate_multi",
        lambda state: "execute_multi" if state.get("final_status") == "multi_validated" else "graceful_failure",
        {"execute_multi": "execute_multi", "graceful_failure": "graceful_failure"},
    )
    graph.add_conditional_edges(
        "execute_multi",
        lambda state: "generate_multi_response" if state.get("final_status") == "multi_ready" else "graceful_failure",
        {"generate_multi_response": "generate_multi_response", "graceful_failure": "graceful_failure"},
    )
    graph.add_edge("generate_multi_response", END)
    graph.add_edge("inspect_schema", "build_query_plan")
    graph.add_conditional_edges(
        "build_query_plan",
        lambda state: "select_dataset" if state.get("final_status") == "reselect" else (
            "execute_query" if "query_plan" in state else "graceful_failure"
        ),
        {"select_dataset": "select_dataset", "execute_query": "execute_query", "graceful_failure": "graceful_failure"},
    )
    graph.add_conditional_edges(
        "execute_query",
        lambda state: "analyze_result" if "query_frame" in state else "graceful_failure",
        {"analyze_result": "analyze_result", "graceful_failure": "graceful_failure"},
    )
    graph.add_edge("analyze_result", "validate_result")
    graph.add_conditional_edges(
        "validate_result",
        lambda state: "generate_visualization" if state["validation"].valid else (
            "graceful_failure" if state.get("final_status") == "unsupported" else "build_query_plan"
        ),
        {
            "generate_visualization": "generate_visualization",
            "build_query_plan": "build_query_plan",
            "graceful_failure": "graceful_failure",
        },
    )
    graph.add_edge("generate_visualization", "generate_response")
    graph.add_edge("generate_response", END)
    graph.add_edge("answer_capability", END)
    graph.add_edge("answer_project", END)
    graph.add_edge("graceful_failure", END)
    return graph.compile()


class TanyaDOSMService:
    def __init__(self, settings: Settings | None = None, *, llm=None, embedder=None, cache=None):
        self.settings = settings or get_settings()
        if llm is None:
            llm = create_chat_model(self.settings)
        if embedder is None:
            embedder = create_embedder(self.settings)
        services = NodeServices(
            catalogue=Catalogue(self.settings.catalogue_path),
            cache=cache or DatasetCache(self.settings.cache_dir / "datasets", self.settings.cache_ttl_hours),
            llm=llm,
            embedder=embedder,
            embedding_cache_dir=self.settings.cache_dir / "embeddings",
            max_retries=self.settings.max_retries,
            min_match_score=self.settings.min_match_score,
            clarification_gap=self.settings.clarification_gap,
            assistant_facts_path=self.settings.assistant_facts_path,
            joins=JoinRegistry(self.settings.joins_path),
            enable_multi_dataset=self.settings.enable_multi_dataset,
            max_plan_steps=self.settings.max_plan_steps,
            max_join_rows=self.settings.max_join_rows,
            natural_project_answers=self.settings.natural_project_answers,
        )
        self.graph = build_graph(services)
        self.llm = llm

    def resolve_question(self, question: str, history: list[dict[str, Any]]) -> str:
        """Resolve a follow-up using a small, trusted-context prompt."""
        if not history:
            return question.strip()
        turns = [
            {key: value for key, value in turn.items() if value is not None}
            for turn in history[-6:]
        ]
        resolver = self.llm.with_structured_output(ContextResolution)
        context = {"previous_turns": turns, "latest_user_message": question.strip()}
        result = resolver.invoke([
            ("system", CONTEXT_SYSTEM),
            ("human", json.dumps(context, ensure_ascii=False)),
        ])
        return result.standalone_question.strip()

    def ask(self, question: str, *, event_sink: Callable[[dict[str, Any]], None] | None = None) -> AnswerPayload:
        if not question.strip():
            raise ValueError("Question cannot be empty")
        initial_state: AgentState = {"question": question.strip(), "retry_count": 0, "errors": []}
        if event_sink is not None:
            initial_state["event_sink"] = event_sink
        state = self.graph.invoke(initial_state)
        return state["answer"]


# Backward-compatible public alias for integrations using the former name.
AskDOSMService = TanyaDOSMService
