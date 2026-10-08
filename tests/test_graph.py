from pathlib import Path
import json

import pandas as pd

from askdosm.agent.graph import build_graph
from askdosm.agent.nodes import NodeServices
from askdosm.agent.nodes import build_query_plan, generate_response
from askdosm.catalogue import Catalogue
from askdosm.models import (
    AnalysisResult, CombineHow, CombineSpec, ContextResolution, FilterSpec, IntentKind,
    MultiPlan, Operation, PlanStep, QueryPlan, QuestionIntent, StepKind,
    ValidationResult, VisualizationSpec,
)
from askdosm.agent.graph import TanyaDOSMService
from askdosm.catalogue import JoinRegistry


class FakeRunnable:
    def __init__(self, value):
        self.value = value

    def invoke(self, messages):
        return self.value


class FakeLLM:
    def __init__(self, intent, plan):
        self.values = {QuestionIntent: intent, QueryPlan: plan}
        self.usage = None

    def with_structured_output(self, schema):
        return FakeRunnable(self.values[schema])


class MultiFakeLLM:
    def __init__(self, intent, multi_plan):
        self.values = {QuestionIntent: intent, MultiPlan: multi_plan}
        self.usage = None

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
        embedder=None, embedding_cache_dir=tmp_path, max_retries=2, enable_multi_dataset=False,
    )
    state = build_graph(services).invoke({"question": "Compare population and unemployment", "retry_count": 0, "errors": []})
    assert state["answer"].error
    assert "one dataset" in state["answer"].answer


def test_capability_question_lists_available_data(tmp_path):
    intent = QuestionIntent(kind=IntentKind.CAPABILITY)
    unused_plan = QueryPlan(dataset_id="population_state", columns=["population"], metric="population", operation=Operation.LOOKUP)
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")), cache=FakeCache(pd.DataFrame()), llm=FakeLLM(intent, unused_plan),
        embedder=None, embedding_cache_dir=tmp_path,
    )
    state = build_graph(services).invoke({"question": "what data do you have", "retry_count": 0, "errors": []})
    assert state["answer"].error is None
    assert "datasets" in state["answer"].answer
    assert state["final_status"] == "capability"


def test_vague_but_answerable_question_proceeds_with_assumptions(tmp_path):
    intent = QuestionIntent(metric="population")
    plan = QueryPlan(
        dataset_id="population_malaysia", columns=["date", "population"], metric="population",
        operation=Operation.LOOKUP,
        filters=[FilterSpec(column="date", operator="eq", value="2025-01-01")],
    )
    frame = pd.DataFrame(
        {"date": pd.to_datetime(["2025-01-01"]), "sex": ["both"], "age": ["overall"],
         "ethnicity": ["overall"], "population": [34000.0]}
    )
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")), cache=FakeCache(frame), llm=FakeLLM(intent, plan),
        embedder=None, embedding_cache_dir=tmp_path, min_match_score=0.10, clarification_gap=0.03,
    )
    state = build_graph(services).invoke({"question": "population", "retry_count": 0, "errors": []})
    assert state["answer"].error is None
    assert state["answer"].assumptions
    assert any("national" in note for note in state["answer"].assumptions)


def test_off_topic_question_is_rejected(tmp_path):
    intent = QuestionIntent(metric="happiness")
    unused_plan = QueryPlan(dataset_id="population_state", columns=["population"], metric="population", operation=Operation.LOOKUP)
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")), cache=FakeCache(pd.DataFrame()), llm=FakeLLM(intent, unused_plan),
        embedder=None, embedding_cache_dir=tmp_path, min_match_score=0.10, clarification_gap=0.03,
    )
    state = build_graph(services).invoke({"question": "how many people are happy today", "retry_count": 0, "errors": []})
    assert state["answer"].error


def test_planner_dataset_mismatch_recovers_without_crashing(tmp_path):
    intent = QuestionIntent(metric="population", geography_level="state", entities=["Selangor"])
    # Planner insists on a different dataset than the one that was selected first.
    mismatched_plan = QueryPlan(
        dataset_id="population_malaysia", columns=["date", "population"], metric="population",
        operation=Operation.LOOKUP,
    )
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")), cache=FakeCache(pd.DataFrame()), llm=FakeLLM(intent, mismatched_plan),
        embedder=None, embedding_cache_dir=tmp_path,
    )
    state = build_graph(services).invoke({"question": "population of Selangor", "retry_count": 0, "errors": []})
    assert state["final_status"] in {"failed", "unsupported"}
    assert state["answer"].error


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


def test_service_resolves_follow_up_with_bounded_structured_context():
    class ResolverLLM:
        usage = None

        def with_structured_output(self, schema):
            assert schema is ContextResolution
            return FakeRunnable(ContextResolution(
                standalone_question="What was Selangor's population in 2025?"
            ))

    service = object.__new__(TanyaDOSMService)
    service.llm = ResolverLLM()
    history = [
        {"user": f"Question {index}", "resolved": f"Resolved {index}", "assistant": f"Answer {index}"}
        for index in range(10)
    ]

    resolved = service.resolve_question("What about Selangor?", history)

    assert resolved == "What was Selangor's population in 2025?"


def _multi_cache(frames):
    class _Cache:
        def load(self, definition):
            return frames[definition.dataset_id].copy()

        def freshness(self, dataset_id):
            return "fixture"

    return _Cache()


def test_multi_dataset_ratio_is_whitelisted_and_executes(tmp_path):
    intent = QuestionIntent(multi_dataset=True, metric="gdp", operation=Operation.COMPARE)
    plan = MultiPlan(
        steps=[
            PlanStep(
                step_id="s1", kind=StepKind.FETCH, dataset_id="gdp_gni_annual_nominal",
                plan=QueryPlan(
                    dataset_id="gdp_gni_annual_nominal", columns=["date", "gdp"], metric="gdp",
                    operation=Operation.LOOKUP,
                    filters=[FilterSpec(column="date", operator="eq", value="2020-01-01")],
                ),
            ),
            PlanStep(
                step_id="s2", kind=StepKind.FETCH, dataset_id="population_malaysia",
                plan=QueryPlan(
                    dataset_id="population_malaysia", columns=["date", "population"], metric="population",
                    operation=Operation.LOOKUP,
                    filters=[FilterSpec(column="date", operator="eq", value="2020-01-01")],
                ),
            ),
            PlanStep(
                step_id="s3", kind=StepKind.COMBINE,
                combine=CombineSpec(how=CombineHow.RATIO, left="s1", right="s2", on=["date"],
                                    left_metric="gdp", right_metric="population"),
                output_metric="gdp_per_capita",
            ),
        ],
        final_step="s3",
    )
    frames = {
        "gdp_gni_annual_nominal": pd.DataFrame(
            {"date": pd.to_datetime(["2020-01-01"]), "series": ["gdp"], "gdp": [1342000.0], "gni": [1300000.0]}
        ),
        "population_malaysia": pd.DataFrame(
            {"date": pd.to_datetime(["2020-01-01"]), "sex": ["both"], "age": ["overall"],
             "ethnicity": ["overall"], "population": [32600.0]}
        ),
    }
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")), cache=_multi_cache(frames),
        llm=MultiFakeLLM(intent, plan), embedder=None, embedding_cache_dir=tmp_path,
        joins=JoinRegistry(Path("data/joins.json")), enable_multi_dataset=True, max_plan_steps=3,
    )
    state = build_graph(services).invoke({"question": "GDP per capita 2020", "retry_count": 0, "errors": []})
    assert state["answer"].error is None
    assert state["final_status"] == "complete"
    assert len(state["answer"].sources) == 2
    assert state["answer"].table_rows[0]["gdp_per_capita"] > 0


def test_multi_dataset_non_whitelisted_join_is_refused(tmp_path):
    intent = QuestionIntent(multi_dataset=True, operation=Operation.COMPARE)
    plan = MultiPlan(
        steps=[
            PlanStep(step_id="s1", kind=StepKind.FETCH, dataset_id="population_malaysia",
                     plan=QueryPlan(dataset_id="population_malaysia", columns=["date", "population"],
                                    metric="population", operation=Operation.LOOKUP)),
            PlanStep(step_id="s2", kind=StepKind.FETCH, dataset_id="lfs_month",
                     plan=QueryPlan(dataset_id="lfs_month", columns=["date", "u_rate"],
                                    metric="u_rate", operation=Operation.LOOKUP)),
            PlanStep(step_id="s3", kind=StepKind.COMBINE,
                     combine=CombineSpec(how=CombineHow.RATIO, left="s1", right="s2", on=["date"],
                                         left_metric="population", right_metric="u_rate")),
        ],
        final_step="s3",
    )
    services = NodeServices(
        catalogue=Catalogue(Path("data/catalogue.json")), cache=FakeCache(pd.DataFrame()),
        llm=MultiFakeLLM(intent, plan), embedder=None, embedding_cache_dir=tmp_path,
        joins=JoinRegistry(Path("data/joins.json")), enable_multi_dataset=True, max_plan_steps=3,
    )
    state = build_graph(services).invoke({"question": "population per unemployment", "retry_count": 0, "errors": []})
    assert state["answer"].error
    assert "whitelisted" in state["answer"].answer
