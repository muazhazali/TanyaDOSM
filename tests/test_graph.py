from pathlib import Path
import json

import pandas as pd

from askdosm.agent.graph import build_graph
from askdosm.agent.nodes import NodeServices
from askdosm.agent.nodes import build_query_plan, generate_response
from askdosm.catalogue import Catalogue
from askdosm.models import (
    AnalysisResult, FilterSpec, Operation, QueryPlan, QuestionIntent,
    ValidationResult, VisualizationSpec,
)


class FakeRunnable:
    def __init__(self, value):
        self.value = value

    def invoke(self, messages):
        return self.value


class FakeLLM:
    def __init__(self, intent, plan):
        self.values = {QuestionIntent: intent, QueryPlan: plan}

    def with_structured_output(self, schema):
        return FakeRunnable(self.values[schema])


class FakeCache:
    def __init__(self, frame):
        self.frame = frame

    def load(self, definition):
        return self.frame.copy()

    def freshness(self, dataset_id):
        return "fixture"


def test_graph_returns_validated_answer(tmp_path):
    intent = QuestionIntent(
        domain="demography", metric="population", geography_level="state", entities=["Selangor"],
        start_period="2025", end_period="2025", operation=Operation.LOOKUP
    )
    plan = QueryPlan(
        dataset_id="population_state", columns=["date", "state", "population"],
        filters=[FilterSpec(column="state", operator="eq", value="Selangor"), FilterSpec(column="date", operator="eq", value="2025-01-01")],
        metric="population", operation=Operation.LOOKUP
    )
    frame = pd.DataFrame(
        {"date": pd.to_datetime(["2025-01-01"]), "state": ["Selangor"], "sex": ["both"], "age": ["overall"],
         "ethnicity": ["overall"], "population": [7100.0]}
    )
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")), cache=FakeCache(frame), llm=FakeLLM(intent, plan),
        embedder=None, embedding_cache_dir=tmp_path, max_retries=2
    )
    events = []
    state = build_graph(services).invoke({"question": "What was Selangor's population in 2025?", "retry_count": 0, "errors": [], "event_sink": events.append})
    assert state["answer"].error is None
    assert "7,100 thousand people" in state["answer"].answer
    assert state["answer"].source.dataset_id == "population_state"
    assert any(event["type"] == "query_plan" for event in events)
    assert any(event["type"] == "data_summary" for event in events)
    json.dumps(events, allow_nan=False)


def test_graph_rejects_multi_dataset_question(tmp_path):
    intent = QuestionIntent(multi_dataset=True, operation=Operation.COMPARE)
    unused_plan = QueryPlan(dataset_id="population_state", columns=["population"], metric="population", operation=Operation.LOOKUP)
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")), cache=FakeCache(pd.DataFrame()), llm=FakeLLM(intent, unused_plan),
        embedder=None, embedding_cache_dir=tmp_path, max_retries=2
    )
    state = build_graph(services).invoke({"question": "Compare population and unemployment", "retry_count": 0, "errors": []})
    assert state["answer"].error
    assert "one dataset" in state["answer"].answer


def test_latest_instruction_is_not_used_as_a_date_filter(tmp_path):
    intent = QuestionIntent(
        domain="demography", metric="population", geography_level="national", latest=True
    )
    plan = QueryPlan(
        dataset_id="population_malaysia",
        columns=["date", "population"],
        filters=[FilterSpec(column="date", operator="eq", value="latest")],
        metric="population",
        operation=Operation.LOOKUP,
    )
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")),
        cache=FakeCache(pd.DataFrame()),
        llm=FakeLLM(intent, plan),
        embedder=None,
        embedding_cache_dir=tmp_path,
    )
    state = {
        "question": "What is Malaysia's latest population?",
        "intent": intent,
        "selected_dataset": services.catalogue.get("population_malaysia"),
    }

    result = build_query_plan(state, services)

    assert result["query_plan"].filters == []


def test_malay_minimum_answer_names_the_matching_state(tmp_path):
    catalogue = Catalogue(Path("data/catalogue.json"))
    intent = QuestionIntent(language="ms", domain="demography", metric="population", geography_level="state")
    query_plan = QueryPlan(
        dataset_id="population_state", columns=["state", "population"],
        metric="population", operation=Operation.MIN,
    )
    analysis = AnalysisResult(
        rows=[
            {"state": "Selangor", "population": 7363.4},
            {"state": "W.P. Labuan", "population": 52.9},
        ],
        supporting_values={"minimum": 52.9}, calculation="minimum(population)",
        metric="population", unit="thousand people", row_count=2, result_kind="calculated",
    )
    services = NodeServices(
        catalogue=catalogue, cache=FakeCache(pd.DataFrame()), llm=FakeLLM(intent, query_plan),
        embedder=None, embedding_cache_dir=tmp_path,
    )
    state = {
        "intent": intent,
        "selected_dataset": catalogue.get("population_state"),
        "query_plan": query_plan,
        "analysis_result": analysis,
        "visualization": VisualizationSpec(),
        "validation": ValidationResult(valid=True, status="valid"),
    }

    answer = generate_response(state, services)["answer"].answer

    assert "W.P. Labuan" in answer
    assert "52.9 ribu orang" in answer
    assert "paling sedikit" in answer
