"""Dataset caching, schema validation, and constrained querying."""

from __future__ import annotations

import os
import re
import tempfile
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from askdosm.models import DatasetDefinition, FilterSpec, QueryPlan


STATE_ALIASES = {
    "penang": "Pulau Pinang",
    "pulau pinang": "Pulau Pinang",
    "kuala lumpur": "W.P. Kuala Lumpur",
    "wp kuala lumpur": "W.P. Kuala Lumpur",
    "w.p. kuala lumpur": "W.P. Kuala Lumpur",
    "putrajaya": "W.P. Putrajaya",
    "labuan": "W.P. Labuan",
    "negeri sembilan": "Negeri Sembilan",
    "n sembilan": "Negeri Sembilan",
}


def normalize_entity(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    return STATE_ALIASES.get(cleaned.casefold(), cleaned.title())


def validate_schema(frame: pd.DataFrame, definition: DatasetDefinition) -> None:
    missing = sorted(set(definition.expected_schema) - set(frame.columns))
    if missing:
        raise ValueError(f"Dataset {definition.dataset_id} is missing columns: {', '.join(missing)}")
    for column, expected in definition.expected_schema.items():
        series = frame[column]
        if expected == "number" and not pd.api.types.is_numeric_dtype(series):
            raise ValueError(f"Column {column} must be numeric")
        if expected == "date" and not (
            pd.api.types.is_datetime64_any_dtype(series) or pd.api.types.is_object_dtype(series)
        ):
            raise ValueError(f"Column {column} must contain dates")


class DatasetCache:
    def __init__(self, directory: Path, ttl_hours: int = 24):
        self.directory = directory
        self.ttl = timedelta(hours=ttl_hours)

    def path_for(self, dataset_id: str) -> Path:
        return self.directory / f"{dataset_id}.parquet"

    def _is_fresh(self, path: Path) -> bool:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return datetime.now(tz=UTC) - modified <= self.ttl

    def freshness(self, dataset_id: str) -> str | None:
        path = self.path_for(dataset_id)
        if not path.exists():
            return None
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return f"cached {modified.isoformat(timespec='seconds')}"

    def load(self, definition: DatasetDefinition, *, force_refresh: bool = False) -> pd.DataFrame:
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.path_for(definition.dataset_id)
        if destination.exists() and not force_refresh and self._is_fresh(destination):
            frame = pd.read_parquet(destination)
            validate_schema(frame, definition)
            return self._normalize(frame)

        try:
            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False, dir=self.directory) as temp:
                temp_path = Path(temp.name)
            urllib.request.urlretrieve(str(definition.parquet_url), temp_path)
            candidate = pd.read_parquet(temp_path)
            validate_schema(candidate, definition)
            os.replace(temp_path, destination)
            return self._normalize(candidate)
        except Exception:
            if "temp_path" in locals():
                temp_path.unlink(missing_ok=True)
            if destination.exists():
                frame = pd.read_parquet(destination)
                validate_schema(frame, definition)
                return self._normalize(frame)
            raise

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        if "date" in result:
            result["date"] = pd.to_datetime(result["date"], errors="coerce")
        return result


def _coerce_filter_value(column: str, value: Any) -> Any:
    if column == "state":
        if isinstance(value, list):
            return [normalize_entity(str(item)) for item in value]
        return normalize_entity(str(value))
    if column == "date":
        if isinstance(value, list):
            return [pd.Timestamp(item) for item in value]
        return pd.Timestamp(value)
    return value


def apply_filter(frame: pd.DataFrame, spec: FilterSpec) -> pd.DataFrame:
    if spec.column not in frame.columns:
        raise ValueError(f"Unknown filter column: {spec.column}")
    value = _coerce_filter_value(spec.column, spec.value)
    series = frame[spec.column]
    if spec.operator == "eq":
        return frame.loc[series == value]
    if spec.operator == "in":
        if not isinstance(value, list):
            raise ValueError("The 'in' operator requires a list")
        return frame.loc[series.isin(value)]
    if spec.operator == "gte":
        return frame.loc[series >= value]
    if spec.operator == "lte":
        return frame.loc[series <= value]
    if spec.operator == "between":
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("The 'between' operator requires exactly two values")
        return frame.loc[series.between(value[0], value[1], inclusive="both")]
    raise ValueError(f"Unsupported filter operator: {spec.operator}")


def execute_plan(frame: pd.DataFrame, definition: DatasetDefinition, plan: QueryPlan) -> pd.DataFrame:
    if plan.dataset_id != definition.dataset_id:
        raise ValueError("Query plan dataset does not match selected dataset")
    allowed = set(definition.dimensions) | {measure.name for measure in definition.measures}
    referenced = set(plan.columns) | set(plan.group_by) | {item.column for item in plan.filters}
    invalid = sorted(referenced - allowed)
    if invalid:
        raise ValueError(f"Query plan references disallowed columns: {', '.join(invalid)}")
    if plan.metric not in {measure.name for measure in definition.measures}:
        raise ValueError(f"Unsupported metric for {definition.dataset_id}: {plan.metric}")

    result = frame.copy()
    explicit_columns = {item.column for item in plan.filters}
    for column, value in definition.default_filters.items():
        if column not in explicit_columns:
            result = apply_filter(result, FilterSpec(column=column, operator="eq", value=value))
    for spec in plan.filters:
        result = apply_filter(result, spec)

    selected = list(dict.fromkeys([*plan.columns, *plan.group_by]))
    result = result.loc[:, selected]
    if plan.sort:
        result = result.sort_values(plan.metric, ascending=plan.sort == "asc")
    if plan.limit:
        result = result.head(plan.limit)
    return result.reset_index(drop=True)


def resolve_latest(frame: pd.DataFrame) -> pd.DataFrame:
    if "date" not in frame.columns or frame.empty:
        return frame
    return frame.loc[frame["date"] == frame["date"].max()].reset_index(drop=True)
