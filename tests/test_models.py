import pytest
from pydantic import ValidationError

from askdosm.models import Operation, QueryPlan


def test_query_plan_forbids_extra_fields_and_caps_limit():
    with pytest.raises(ValidationError):
        QueryPlan(
            dataset_id="population_state",
            columns=["population"],
            metric="population",
            operation=Operation.RANKING,
            limit=1000,
            sql="select *",
        )


def test_metric_is_always_selected():
    plan = QueryPlan(dataset_id="lfs_month", columns=["date"], metric="u_rate", operation=Operation.TREND)
    assert plan.columns == ["date", "u_rate"]

