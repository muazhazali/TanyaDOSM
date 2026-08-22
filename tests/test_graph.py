from pathlib import Path

import pandas as pd

from askdosm.agent.graph import build_graph
from askdosm.agent.nodes import NodeServices
from askdosm.catalogue import Catalogue
from askdosm.models import FilterSpec, Operation, QueryPlan, QuestionIntent


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
    state = build_graph(services).invoke({"question": "What was Selangor's population in 2025?", "retry_count": 0, "errors": []})
    assert state["answer"].error is None
    assert "7,100 thousand people" in state["answer"].answer
    assert state["answer"].source.dataset_id == "population_state"


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

