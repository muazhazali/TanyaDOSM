"""Validated contracts shared by deterministic and agentic layers."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


def _drop_nulls(values: Any) -> Any:
    """Strip ``None`` values so Pydantic applies field defaults.

    Hosted models (notably Ollama Cloud's gpt-oss) emit ``null`` for fields
    they leave unset, even when the schema marks them non-optional with a
    default. Removing those keys lets Pydantic substitute the default.
    """
    if isinstance(values, dict):
        return {key: value for key, value in values.items() if value is not None}
    return values


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


class IntentKind(StrEnum):
    DATA = "data"
    CAPABILITY = "capability"
    PROJECT = "project"


class StepKind(StrEnum):
    FETCH = "fetch"
    COMBINE = "combine"


class CombineHow(StrEnum):
    CONCAT = "concat"
    JOIN = "join"
    RATIO = "ratio"
    DIFFERENCE = "difference"


class QuestionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language = Language.EN
    kind: IntentKind = IntentKind.DATA
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
    sub_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_nulls(cls, values: Any) -> Any:
        return _drop_nulls(values)


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


JsonScalar: TypeAlias = str | int | float | bool | None


class FilterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    operator: Literal["eq", "in", "gte", "lte", "between"]
    value: JsonScalar | list[JsonScalar]


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

    @model_validator(mode="before")
    @classmethod
    def _normalize_nulls(cls, values: Any) -> Any:
        return _drop_nulls(values)

    @model_validator(mode="after")
    def metric_must_be_selected(self) -> "QueryPlan":
        if self.metric not in self.columns:
            self.columns.append(self.metric)
        return self


class CombineSpec(BaseModel):
    """A deterministic combination of two earlier steps. No code, no SQL."""

    model_config = ConfigDict(extra="forbid")

    how: CombineHow
    left: str
    right: str
    on: list[str] = Field(default_factory=list)
    left_metric: str | None = None
    right_metric: str | None = None
    method: Literal["inner", "left"] = "inner"

    @model_validator(mode="before")
    @classmethod
    def _normalize_nulls(cls, values: Any) -> Any:
        return _drop_nulls(values)


class PlanStep(BaseModel):
    """One node of the multi-dataset DAG: either a fetch or a combine."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    kind: StepKind
    dataset_id: str | None = None
    plan: QueryPlan | None = None
    combine: CombineSpec | None = None
    output_metric: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_nulls(cls, values: Any) -> Any:
        return _drop_nulls(values)


class MultiPlan(BaseModel):
    """A declarative, catalogue-validated DAG of dataset operations."""

    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep]
    final_step: str

    @model_validator(mode="before")
    @classmethod
    def _normalize_nulls(cls, values: Any) -> Any:
        return _drop_nulls(values)


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

    @model_validator(mode="before")
    @classmethod
    def _normalize_nulls(cls, values: Any) -> Any:
        return _drop_nulls(values)


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


class TokenUsage(BaseModel):
    """Accumulated token usage for a single run, with estimated cost in USD.

    Prices are per 1 million tokens. ``cached_input_price`` applies to the
    cached portion of the prompt tokens; non-cached prompt tokens use
    ``input_price``. Cost estimates are derived from the provider's public
    price sheet and are not billing-accurate.
    """

    model: str = ""
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    input_price_per_m: float = 0.0
    cached_input_price_per_m: float = 0.0
    output_price_per_m: float = 0.0

    def add(self, prompt: int, completion: int, cached: int = 0) -> None:
        """Accumulate a single LLM call's tokens and recompute the cost."""
        self.prompt_tokens += max(0, int(prompt))
        self.completion_tokens += max(0, int(completion))
        self.cached_prompt_tokens += max(0, int(cached))
        self.total_tokens = self.prompt_tokens + self.completion_tokens
        self._recompute_cost()

    def _recompute_cost(self) -> None:
        non_cached = max(0, self.prompt_tokens - self.cached_prompt_tokens)
        cost = (
            non_cached * self.input_price_per_m
            + self.cached_prompt_tokens * self.cached_input_price_per_m
            + self.completion_tokens * self.output_price_per_m
        ) / 1_000_000
        self.estimated_cost_usd = round(cost, 6)


class ExecutionTrace(BaseModel):
    intent: QuestionIntent | None = None
    selection_reason: str | None = None
    query_plan: QueryPlan | None = None
    calculation: str | None = None
    rows_used: int = 0
    validation: ValidationResult | None = None
    retry_count: int = 0
    token_usage: TokenUsage | None = None


class AnswerPayload(BaseModel):
    answer: str
    table_rows: list[dict[str, Any]] = Field(default_factory=list)
    visualization: VisualizationSpec = Field(default_factory=VisualizationSpec)
    source: SourceReference | None = None
    sources: list[SourceReference] = Field(default_factory=list)
    trace: ExecutionTrace = Field(default_factory=ExecutionTrace)
    error: str | None = None
    follow_ups: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
class ContextResolution(BaseModel):
    """A standalone question reconstructed from bounded conversation context."""

    model_config = ConfigDict(extra="forbid")
    standalone_question: str = Field(min_length=1, max_length=500)
