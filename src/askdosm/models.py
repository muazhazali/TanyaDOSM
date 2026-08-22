"""Validated contracts shared by deterministic and agentic layers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class Language(StrEnum):
    EN = "en"
    MS = "ms"


class Operation(StrEnum):
    LOOKUP = "lookup"
    SUM = "sum"
    COUNT = "count"
    MEAN = "mean"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    DIFFERENCE = "difference"
    PERCENTAGE_DIFFERENCE = "percentage_difference"
    YOY_CHANGE = "year_over_year_change"
    PERCENTAGE_GROWTH = "percentage_growth"
    CAGR = "cagr"
    RANKING = "ranking"
    COMPARE = "compare"
    TREND = "trend"


class OutputKind(StrEnum):
    NONE = "none"
    LINE = "line"
    BAR = "bar"
    RANKING_BAR = "ranking_bar"
    TABLE = "table"


class QuestionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language = Language.EN
    domain: str | None = None
    metric: str | None = None
    geography_level: Literal["national", "state", "district"] | None = None
    entities: list[str] = Field(default_factory=list)
    start_period: str | None = None
    end_period: str | None = None
    latest: bool = False
    operation: Operation = Operation.LOOKUP
    requested_output: OutputKind | None = None
    ambiguous: bool = False
    clarification: str | None = None
    multi_dataset: bool = False


class MeasureDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    aliases: list[str]
    unit: str


class DatasetDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    title: str
    description: str
    domain: str
    aliases: list[str]
    dimensions: list[str]
    measures: list[MeasureDefinition]
    frequency: Literal["monthly", "quarterly", "annual"]
    geography_level: Literal["national", "state", "district"]
    source_agency: str
    source_url: HttpUrl
    parquet_url: HttpUrl
    caveats: list[str] = Field(default_factory=list)
    expected_schema: dict[str, str]
    default_filters: dict[str, Any] = Field(default_factory=dict)

    @property
    def searchable_text(self) -> str:
        measure_text = " ".join(
            item for measure in self.measures for item in [measure.name, *measure.aliases]
        )
        return " ".join(
            [self.title, self.description, self.domain, self.geography_level, *self.aliases, measure_text]
        )


class DatasetCandidate(BaseModel):
    dataset_id: str
    score: float
    reason: str


class FilterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    operator: Literal["eq", "in", "gte", "lte", "between"]
    value: Any


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    columns: list[str]
    filters: list[FilterSpec] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    metric: str
    operation: Operation
    sort: Literal["asc", "desc"] | None = None
    limit: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def metric_must_be_selected(self) -> "QueryPlan":
        if self.metric not in self.columns:
            self.columns.append(self.metric)
        return self


class AnalysisResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    supporting_values: dict[str, float | int | str | None] = Field(default_factory=dict)
    calculation: str | None = None
    metric: str
    unit: str
    row_count: int
    result_kind: Literal["retrieved", "calculated"] = "retrieved"


class ValidationResult(BaseModel):
    valid: bool
    status: Literal["valid", "invalid_query", "wrong_dataset", "unsupported"]
    errors: list[str] = Field(default_factory=list)
    retry_action: Literal["search_catalogue", "build_query_plan", "graceful_failure"] | None = None


class VisualizationSpec(BaseModel):
    kind: OutputKind = OutputKind.NONE
    x: str | None = None
    y: str | None = None
    color: str | None = None
    title: str | None = None


class SourceReference(BaseModel):
    dataset_id: str
    title: str
    agency: str
    url: HttpUrl
    period: str | None = None
    unit: str
    cache_freshness: str | None = None


class ExecutionTrace(BaseModel):
    intent: QuestionIntent | None = None
    selection_reason: str | None = None
    query_plan: QueryPlan | None = None
    calculation: str | None = None
    rows_used: int = 0
    validation: ValidationResult | None = None
    retry_count: int = 0


class AnswerPayload(BaseModel):
    answer: str
    table_rows: list[dict[str, Any]] = Field(default_factory=list)
    visualization: VisualizationSpec = Field(default_factory=VisualizationSpec)
    source: SourceReference | None = None
    trace: ExecutionTrace = Field(default_factory=ExecutionTrace)
    error: str | None = None
