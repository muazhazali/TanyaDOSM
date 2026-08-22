"""Compiled AskDOSM LangGraph and public service facade."""

from __future__ import annotations

from pathlib import Path

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.graph import END, START, StateGraph

from askdosm.agent import nodes
from askdosm.agent.nodes import NodeServices
from askdosm.agent.state import AgentState
from askdosm.catalogue import Catalogue
from askdosm.config import Settings, get_settings
from askdosm.data import DatasetCache
from askdosm.models import AnswerPayload


def build_graph(services: NodeServices):
    graph = StateGraph(AgentState)
    graph.add_node("parse_question", lambda state: nodes.parse_question(state, services))
    graph.add_node("search_catalogue", lambda state: nodes.search_catalogue(state, services))
    graph.add_node("select_dataset", lambda state: nodes.select_dataset(state, services))
    graph.add_node("inspect_schema", lambda state: nodes.inspect_schema(state, services))
    graph.add_node("build_query_plan", lambda state: nodes.build_query_plan(state, services))
    graph.add_node("execute_query", lambda state: nodes.execute_query(state, services))
    graph.add_node("analyze_result", lambda state: nodes.analyze_result(state, services))
    graph.add_node("validate_result", lambda state: nodes.validate_result_node(state, services))
    graph.add_node("generate_visualization", lambda state: nodes.generate_visualization(state, services))
    graph.add_node("generate_response", lambda state: nodes.generate_response(state, services))
    graph.add_node("graceful_failure", lambda state: nodes.graceful_failure(state, services))

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


class AskDOSMService:
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

    def ask(self, question: str) -> AnswerPayload:
        if not question.strip():
            raise ValueError("Question cannot be empty")
        state = self.graph.invoke({"question": question.strip(), "retry_count": 0, "errors": []})
        return state["answer"]
