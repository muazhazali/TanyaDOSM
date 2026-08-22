"""Deterministic, framework-independent visualization selection."""

from __future__ import annotations

from askdosm.models import AnalysisResult, Operation, OutputKind, QueryPlan, VisualizationSpec


def choose_visualization(result: AnalysisResult, plan: QueryPlan) -> VisualizationSpec:
    if result.row_count <= 1:
        return VisualizationSpec()
    columns = set(result.rows[0]) if result.rows else set()
    entity = "state" if "state" in columns else None
    if plan.operation == Operation.RANKING and entity:
        return VisualizationSpec(kind=OutputKind.RANKING_BAR, x=result.metric, y=entity, title=f"Ranking by {result.metric}")
    if "date" in columns:
        return VisualizationSpec(kind=OutputKind.LINE, x="date", y=result.metric, color=entity, title=f"{result.metric} over time")
    if entity:
        return VisualizationSpec(kind=OutputKind.BAR, x=entity, y=result.metric, title=f"{result.metric} comparison")
    return VisualizationSpec(kind=OutputKind.TABLE)
