"""Deterministic visualization selection and Plotly construction."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure

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


def build_figure(rows: list[dict], spec: VisualizationSpec) -> Figure | None:
    if spec.kind in {OutputKind.NONE, OutputKind.TABLE} or not rows:
        return None
    frame = pd.DataFrame(rows)
    if spec.kind == OutputKind.LINE:
        return px.line(frame, x=spec.x, y=spec.y, color=spec.color, markers=True, title=spec.title)
    if spec.kind == OutputKind.RANKING_BAR:
        return px.bar(frame, x=spec.x, y=spec.y, orientation="h", title=spec.title)
    return px.bar(frame, x=spec.x, y=spec.y, color=spec.color, title=spec.title)
