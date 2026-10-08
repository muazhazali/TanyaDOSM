"""Deterministic combination of two step results (no LLM, no SQL)."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from askdosm.models import CombineHow, CombineSpec


class CombineError(ValueError):
    """Raised when a combination cannot be performed safely."""


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise CombineError(f"{label} is missing columns for combination: {', '.join(missing)}")


def combine(
    left: pd.DataFrame,
    right: pd.DataFrame,
    spec: CombineSpec,
    *,
    left_metric: str | None = None,
    right_metric: str | None = None,
    output_metric: str | None = None,
    max_rows: int = 50_000,
) -> pd.DataFrame:
    """Combine two frames deterministically. Raises CombineError on mismatch."""
    if left.empty or right.empty:
        raise CombineError("One of the inputs to the combination is empty.")

    lm = spec.left_metric or left_metric
    rm = spec.right_metric or right_metric

    if spec.how == CombineHow.CONCAT:
        _require_columns(left, spec.on, "Left input")
        _require_columns(right, spec.on, "Right input")
        merged = left.merge(right, on=spec.on, how="outer", suffixes=("", "_right"))
    elif spec.how == CombineHow.JOIN:
        if not spec.on:
            raise CombineError("A join requires at least one key.")
        _require_columns(left, spec.on, "Left input")
        _require_columns(right, spec.on, "Right input")
        merged = left.merge(right, on=spec.on, how=spec.method, suffixes=("", "_right"))
    elif spec.how in {CombineHow.RATIO, CombineHow.DIFFERENCE}:
        if not lm or not rm:
            raise CombineError("Ratio and difference require both metrics.")
        if not spec.on:
            raise CombineError(f"{spec.how} requires at least one alignment key.")
        _require_columns(left, [*spec.on, lm], "Left input")
        _require_columns(right, [*spec.on, rm], "Right input")
        merged = left[[*spec.on, lm]].merge(
            right[[*spec.on, rm]], on=spec.on, how=spec.method, suffixes=("", "_right")
        )
        numerator = pd.to_numeric(merged[lm], errors="coerce")
        denominator = pd.to_numeric(merged[rm], errors="coerce")
        name = output_metric or f"{lm}_per_{rm}"
        if spec.how == CombineHow.RATIO:
            with_division = denominator.replace(0, math.nan)
            merged[name] = numerator / with_division
        else:
            merged[name] = numerator - denominator
        merged = merged.loc[:, [*spec.on, name]].dropna(subset=[name]).reset_index(drop=True)
    else:  # pragma: no cover - guarded by the enum
        raise CombineError(f"Unsupported combination: {spec.how}")

    if len(merged) > max_rows:
        raise CombineError(f"The combination produced {len(merged)} rows, above the allowed limit.")
    return merged.reset_index(drop=True)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    normalized = frame.copy()
    for column in normalized.select_dtypes(include=["datetime", "datetimetz"]).columns:
        normalized[column] = normalized[column].dt.strftime("%Y-%m-%d")
    return normalized.where(pd.notna(normalized), None).to_dict(orient="records")
