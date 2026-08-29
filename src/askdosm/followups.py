"""Deterministic follow-up question suggestions derived from catalogue metadata."""

from __future__ import annotations

from askdosm.models import (
    AnalysisResult,
    DatasetDefinition,
    Language,
    Operation,
    QueryPlan,
    QuestionIntent,
)

_BREAKDOWN_LABELS_EN: dict[str, str] = {
    "sex": "sex",
    "age": "age group",
    "ethnicity": "ethnicity",
    "category": "category",
    "sector": "sector",
    "education": "education level",
    "marital_status": "marital status",
}
_BREAKDOWN_LABELS_MS: dict[str, str] = {
    "sex": "jantina",
    "age": "kumpulan umur",
    "ethnicity": "kaum",
    "category": "kategori",
    "sector": "sektor",
    "education": "tahap pendidikan",
    "marital_status": "status perkahwinan",
}


def _measure_display(name: str, language: Language) -> str:
    if language == Language.MS:
        return {
            "population": "populasi",
            "u_rate": "kadar pengangguran",
            "lf_unemployed": "bilangan penganggur",
            "p_rate": "kadar penyertaan",
            "lf": "tenaga buruh",
            "inflation_yoy": "kadar inflasi",
        }.get(name, name.replace("_", " "))
    return name.replace("_", " ")


def generate_follow_ups(
    *,
    dataset: DatasetDefinition,
    intent: QuestionIntent,
    plan: QueryPlan,
    result: AnalysisResult,
) -> list[str]:
    """Build up to four deterministic, answerable follow-up questions.

    Suggestions are derived purely from catalogue metadata and the query plan
    that was just executed, so every suggestion is guaranteed to be answerable
    by the same dataset. No LLM call is made.
    """
    language = intent.language
    used_filters = {f.column for f in plan.filters}
    used_group_by = set(plan.group_by)
    metric_display = _measure_display(result.metric, language)
    suggestions: list[str] = []

    has_date = "date" in dataset.dimensions
    time_dims = {"date", "year", "quarter", "month"}
    used_time = used_filters & time_dims or (has_date and plan.operation == Operation.TREND)

    if has_date and plan.operation != Operation.TREND:
        if language == Language.MS:
            suggestions.append(f"Tunjukkan tren {metric_display} dari tahun ke tahun.")
        else:
            suggestions.append(f"Show the trend of {metric_display} over time.")

    breakdown_dims = [
        dim
        for dim in dataset.dimensions
        if dim not in time_dims
        and dim not in used_group_by
        and dim in dataset.default_filters
        and dataset.default_filters.get(dim) == "overall"
    ]
    for dim in breakdown_dims[:1]:
        label = (
            _BREAKDOWN_LABELS_MS.get(dim, dim.replace("_", " "))
            if language == Language.MS
            else _BREAKDOWN_LABELS_EN.get(dim, dim.replace("_", " "))
        )
        if language == Language.MS:
            suggestions.append(f"Pecahkan {metric_display} mengikut {label}.")
        else:
            suggestions.append(f"Break down {metric_display} by {label}.")

    geo_dims = [
        dim for dim in dataset.dimensions if dim in {"state", "district"} and dim not in used_group_by
    ]
    if geo_dims and dataset.geography_level in {"state", "district"}:
        geo = geo_dims[0]
        if language == Language.MS:
            suggestions.append(f"Negeri mana mempunyai {metric_display} tertinggi?")
        else:
            suggestions.append(f"Which {geo} has the highest {metric_display}?")

    other_measures = [
        m.name for m in dataset.measures if m.name != result.metric and m.name not in (plan.columns or [])
    ]
    for measure in other_measures[:1]:
        md = _measure_display(measure, language)
        if language == Language.MS:
            suggestions.append(f"Apakah {md} terkini?")
        else:
            suggestions.append(f"What is the latest {md}?")

    return suggestions[:4]