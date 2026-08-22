"""Deterministic statistical operations."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from askdosm.models import AnalysisResult, DatasetDefinition, Operation, QueryPlan


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    normalized = frame.copy()
    for column in normalized.select_dtypes(include=["datetime", "datetimetz"]).columns:
        normalized[column] = normalized[column].dt.strftime("%Y-%m-%d")
    return normalized.where(pd.notna(normalized), None).to_dict(orient="records")


def _measure(definition: DatasetDefinition, metric: str):
    return next(measure for measure in definition.measures if measure.name == metric)


def analyze(frame: pd.DataFrame, definition: DatasetDefinition, plan: QueryPlan) -> AnalysisResult:
    metric = plan.metric
    unit = _measure(definition, metric).unit
    if frame.empty:
        return AnalysisResult(metric=metric, unit=unit, row_count=0)
    numeric = pd.to_numeric(frame[metric], errors="coerce")
    if numeric.isna().all():
        return AnalysisResult(rows=_records(frame), metric=metric, unit=unit, row_count=len(frame))

    op = plan.operation
    aggregate_ops = {
        Operation.SUM: (numeric.sum, "sum"),
        Operation.COUNT: (numeric.count, "count"),
        Operation.MEAN: (numeric.mean, "mean"),
        Operation.MEDIAN: (numeric.median, "median"),
        Operation.MIN: (numeric.min, "minimum"),
        Operation.MAX: (numeric.max, "maximum"),
    }
    if op in aggregate_ops:
        fn, label = aggregate_ops[op]
        if plan.group_by:
            grouped = frame.groupby(plan.group_by, dropna=False)[metric]
            if op == Operation.MEAN:
                values = grouped.mean()
            elif op == Operation.MEDIAN:
                values = grouped.median()
            elif op == Operation.SUM:
                values = grouped.sum()
            elif op == Operation.MIN:
                values = grouped.min()
            elif op == Operation.MAX:
                values = grouped.max()
            else:
                values = grouped.size()
            grouped_frame = values.rename(metric).reset_index()
            return AnalysisResult(
                rows=_records(grouped_frame), calculation=f"{label}({metric}) grouped by {', '.join(plan.group_by)}",
                metric=metric, unit=unit, row_count=len(frame), result_kind="calculated"
            )
        value = fn()
        return AnalysisResult(
            rows=_records(frame), supporting_values={label: float(value)}, calculation=f"{label}({metric})",
            metric=metric, unit=unit, row_count=len(frame), result_kind="calculated"
        )

    ordered = frame.sort_values("date") if "date" in frame else frame
    values = pd.to_numeric(ordered[metric], errors="coerce").dropna()
    if op in {Operation.DIFFERENCE, Operation.PERCENTAGE_DIFFERENCE, Operation.PERCENTAGE_GROWTH, Operation.CAGR}:
        if plan.group_by:
            output: list[dict[str, Any]] = []
            result_column = "difference" if op == Operation.DIFFERENCE else "cagr" if op == Operation.CAGR else "percentage_growth"
            for keys, group in ordered.groupby(plan.group_by, dropna=False):
                group_values = pd.to_numeric(group[metric], errors="coerce").dropna()
                if len(group_values) < 2:
                    continue
                start, end = float(group_values.iloc[0]), float(group_values.iloc[-1])
                if op == Operation.DIFFERENCE:
                    value = end - start
                elif op in {Operation.PERCENTAGE_DIFFERENCE, Operation.PERCENTAGE_GROWTH}:
                    value = (end - start) / start * 100 if start else math.nan
                else:
                    years = (group["date"].iloc[-1] - group["date"].iloc[0]).days / 365.2425 if "date" in group else 0
                    value = ((end / start) ** (1 / years) - 1) * 100 if years > 0 and start > 0 else math.nan
                key_tuple = keys if isinstance(keys, tuple) else (keys,)
                row = dict(zip(plan.group_by, key_tuple, strict=True))
                row.update({"start": start, "end": end, result_column: value})
                output.append(row)
            result_unit = unit if result_column == "difference" else "percent"
            return AnalysisResult(
                rows=output, calculation=f"{result_column} grouped by {', '.join(plan.group_by)}",
                metric=result_column, unit=result_unit, row_count=len(frame), result_kind="calculated"
            )
        if len(values) < 2:
            return AnalysisResult(rows=_records(frame), metric=metric, unit=unit, row_count=len(frame))
        start, end = float(values.iloc[0]), float(values.iloc[-1])
        difference = end - start
        supporting: dict[str, float] = {"start": start, "end": end}
        if op == Operation.DIFFERENCE:
            supporting["difference"] = difference
            calculation = "end - start"
        elif op in {Operation.PERCENTAGE_DIFFERENCE, Operation.PERCENTAGE_GROWTH}:
            supporting["percentage_growth"] = difference / start * 100 if start else math.nan
            calculation = "(end - start) / start * 100"
        else:
            if "date" not in ordered or start <= 0:
                cagr = math.nan
            else:
                years = (ordered["date"].iloc[-1] - ordered["date"].iloc[0]).days / 365.2425
                cagr = ((end / start) ** (1 / years) - 1) * 100 if years > 0 else math.nan
            supporting["cagr"] = cagr
            calculation = "((end / start) ** (1 / years) - 1) * 100"
        return AnalysisResult(
            rows=_records(ordered), supporting_values=supporting, calculation=calculation,
            metric=metric, unit=unit, row_count=len(frame), result_kind="calculated"
        )

    if op == Operation.YOY_CHANGE:
        changed = ordered.copy()
        periods = 12 if definition.frequency == "monthly" else 4 if definition.frequency == "quarterly" else 1
        changed[f"{metric}_yoy_change"] = pd.to_numeric(changed[metric], errors="coerce").pct_change(periods=periods) * 100
        return AnalysisResult(
            rows=_records(changed), calculation=f"pct_change({periods} periods) * 100",
            metric=metric, unit="percent", row_count=len(changed), result_kind="calculated"
        )

    if op == Operation.RANKING:
        ranking = frame.sort_values(metric, ascending=plan.sort == "asc").copy()
        ranking["rank"] = range(1, len(ranking) + 1)
        return AnalysisResult(
            rows=_records(ranking), calculation=f"rank by {metric}", metric=metric, unit=unit,
            row_count=len(ranking), result_kind="calculated"
        )

    return AnalysisResult(rows=_records(frame), metric=metric, unit=unit, row_count=len(frame))
