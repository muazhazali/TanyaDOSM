from pathlib import Path

import pandas as pd
import pytest

from askdosm.catalogue import Catalogue
from askdosm.data import DatasetCache, execute_plan, normalize_entity, validate_schema
from askdosm.models import FilterSpec, Operation, QueryPlan


@pytest.fixture
def definition():
    return Catalogue(Path("data/catalogue.json")).get("population_state")


@pytest.fixture
def population_frame():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2025-01-01", "2025-01-01"]),
            "state": ["Selangor", "Selangor", "Johor"],
            "sex": ["both"] * 3,
            "age": ["overall"] * 3,
            "ethnicity": ["overall"] * 3,
            "population": [6500.0, 7100.0, 4200.0],
        }
    )


def test_normalize_common_state_aliases():
    assert normalize_entity("penang") == "Pulau Pinang"
    assert normalize_entity("kuala lumpur") == "W.P. Kuala Lumpur"


def test_default_overall_filters_and_user_filters(population_frame, definition):
    plan = QueryPlan(
        dataset_id="population_state",
        columns=["date", "state", "population"],
        filters=[
            FilterSpec(column="state", operator="eq", value="selangor"),
            FilterSpec(column="date", operator="eq", value="2025-01-01"),
        ],
        metric="population",
        operation=Operation.LOOKUP,
    )
    result = execute_plan(population_frame, definition, plan)
    assert result.to_dict(orient="records")[0]["population"] == 7100.0


def test_disallowed_column_is_rejected(population_frame, definition):
    plan = QueryPlan(
        dataset_id="population_state",
        columns=["secret", "population"],
        metric="population",
        operation=Operation.LOOKUP,
    )
    with pytest.raises(ValueError, match="disallowed columns"):
        execute_plan(population_frame, definition, plan)


def test_schema_drift_is_rejected(definition):
    with pytest.raises(ValueError, match="missing columns"):
        validate_schema(pd.DataFrame({"date": ["2025-01-01"]}), definition)


def test_cache_falls_back_to_last_valid_file(tmp_path, population_frame, definition, monkeypatch):
    cache = DatasetCache(tmp_path, ttl_hours=0)
    population_frame.to_parquet(cache.path_for(definition.dataset_id))

    def fail(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr("urllib.request.urlretrieve", fail)
    loaded = cache.load(definition, force_refresh=True)
    assert len(loaded) == 3

