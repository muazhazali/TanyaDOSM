from pathlib import Path

import pandas as pd

from askdosm.analysis import analyze
from askdosm.catalogue import Catalogue
from askdosm.models import Operation, QueryPlan
from askdosm.validation import validate_result
from askdosm.visualization import choose_visualization


def definition():
    return Catalogue(Path("data/catalogue.json")).get("population_state")


def frame():
    return pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-01", "2025-01-01"]), "state": ["Selangor", "Selangor"], "population": [6500.0, 7150.0]}
    )


def plan(operation):
    return QueryPlan(
        dataset_id="population_state", columns=["date", "state", "population"], metric="population", operation=operation
    )


def test_percentage_growth_is_deterministic():
    result = analyze(frame(), definition(), plan(Operation.PERCENTAGE_GROWTH))
    assert result.supporting_values["percentage_growth"] == 10.0
    assert result.result_kind == "calculated"


def test_cagr_uses_elapsed_time():
    result = analyze(frame(), definition(), plan(Operation.CAGR))
    assert 1.9 < result.supporting_values["cagr"] < 2.0


def test_ranking_and_chart_selection():
    ranking_frame = pd.DataFrame({"state": ["Johor", "Selangor"], "population": [4200.0, 7100.0]})
    ranking_plan = plan(Operation.RANKING)
    result = analyze(ranking_frame, definition(), ranking_plan)
    assert result.rows[0]["state"] == "Selangor"
    assert choose_visualization(result, ranking_plan).kind == "ranking_bar"


def test_empty_result_fails_validation():
    query_plan = plan(Operation.LOOKUP)
    result = analyze(frame().iloc[0:0], definition(), query_plan)
    validation = validate_result(result, definition(), query_plan)
    assert not validation.valid
    assert validation.retry_action == "build_query_plan"


def test_grouped_growth_is_calculated_per_entity():
    grouped_frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2025-01-01", "2020-01-01", "2025-01-01"]),
            "state": ["Johor", "Johor", "Selangor", "Selangor"],
            "population": [4000.0, 4400.0, 6500.0, 7150.0],
        }
    )
    grouped_plan = QueryPlan(
        dataset_id="population_state", columns=["date", "state", "population"], group_by=["state"],
        metric="population", operation=Operation.PERCENTAGE_GROWTH
    )
    result = analyze(grouped_frame, definition(), grouped_plan)
    assert result.metric == "percentage_growth"
    assert {row["state"]: row["percentage_growth"] for row in result.rows} == {"Johor": 10.0, "Selangor": 10.0}
