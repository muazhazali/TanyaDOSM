"""Result validation and retry classification."""

from __future__ import annotations

import math

from askdosm.models import AnalysisResult, DatasetDefinition, QueryPlan, ValidationResult


def validate_result(result: AnalysisResult, definition: DatasetDefinition, plan: QueryPlan) -> ValidationResult:
    errors: list[str] = []
    if result.row_count == 0:
        errors.append("No rows matched the requested entities and period.")
    if not result.unit:
        errors.append("The result unit is unknown.")
    if result.rows and any(row.get(result.metric) is None for row in result.rows if result.metric in row):
        errors.append(f"The metric {result.metric} contains missing or non-numeric values.")
    if result.rows:
        normalized_rows = [tuple(sorted((key, str(value)) for key, value in row.items())) for row in result.rows]
        if len(normalized_rows) != len(set(normalized_rows)):
            errors.append("The query returned unexpected duplicate rows.")
    if any(isinstance(value, float) and (math.isnan(value) or math.isinf(value)) for value in result.supporting_values.values()):
        errors.append("The requested calculation is undefined for the selected values.")
    if errors:
        return ValidationResult(
            valid=False,
            status="invalid_query",
            errors=errors,
            retry_action="build_query_plan",
        )
    return ValidationResult(valid=True, status="valid")
