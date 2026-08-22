"""Compiled TanyaDOSM LangGraph and public service facade."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.graph import END, START, StateGraph

from askdosm.agent import nodes
from askdosm.agent.nodes import NodeServices
from askdosm.agent.state import AgentState
from askdosm.catalogue import Catalogue
from askdosm.config import Settings, get_settings
from askdosm.data import DatasetCache
from askdosm.models import AnswerPayload


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
    graph.add_edge("parse_question", "search_catalogue")
    graph.add_edge("search_catalogue", "select_dataset")
    graph.add_conditional_edges(
        "select_dataset",
        lambda state: "inspect_schema" if state.get("final_status") == "selected" else "graceful_failure",
        {"inspect_schema": "inspect_schema", "graceful_failure": "graceful_failure"},
    )
    graph.add_edge("inspect_schema", "build_query_plan")
    graph.add_edge("build_query_plan", "execute_query")
    graph.add_edge("execute_query", "analyze_result")
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
    graph.add_edge("graceful_failure", END)
    return graph.compile()


class TanyaDOSMService:
    def __init__(self, settings: Settings | None = None, *, llm=None, embedder=None, cache=None):
        self.settings = settings or get_settings()
        if llm is None:
            llm = ChatOllama(
                model=self.settings.chat_model,
                base_url=self.settings.ollama_base_url,
                temperature=0,
                validate_model_on_init=True,
            )
        if embedder is None:
            embedder = OllamaEmbeddings(
                model=self.settings.embedding_model,
                base_url=self.settings.ollama_base_url,
            )
        services = NodeServices(
            catalogue=Catalogue(self.settings.catalogue_path),
            cache=cache or DatasetCache(self.settings.cache_dir / "datasets", self.settings.cache_ttl_hours),
            llm=llm,
            embedder=embedder,
            embedding_cache_dir=self.settings.cache_dir / "embeddings",
            max_retries=self.settings.max_retries,
        )
        self.graph = build_graph(services)

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
