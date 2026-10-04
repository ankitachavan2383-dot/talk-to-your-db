"""Chart specs -> Plotly figures. The LLM only proposes a ChartSpec (data); this module renders it."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.analysis.profiler import classify_column, prepare_frame
from app.schemas import ChartSpec

NEEDS_Y = {"bar", "line", "area", "scatter", "box", "pie"}
NEEDS_X = {"bar", "line", "area", "scatter", "histogram", "pie"}


class ChartSpecError(ValueError):
    pass


def validate_spec(df: pd.DataFrame, spec: ChartSpec) -> None:
    for c in (spec.x, spec.y, spec.color):
        if c and c not in df.columns:
            raise ChartSpecError(f"Unknown column '{c}'.")
    t = spec.chart_type
    if t in NEEDS_X and not spec.x:
        raise ChartSpecError(f"{t} chart needs x.")
    if t in NEEDS_Y and not spec.y:
        raise ChartSpecError(f"{t} chart needs y.")
    if spec.y and spec.agg not in ("count", "nunique") and not pd.api.types.is_numeric_dtype(df[spec.y]):
        raise ChartSpecError(f"y column '{spec.y}' must be numeric.")


def build_figure(df: pd.DataFrame, spec: ChartSpec) -> go.Figure:
    validate_spec(df, spec)
    d, t = df, spec.chart_type
    if spec.agg and spec.x and spec.y and t in {"bar", "line", "area", "pie"}:
        keys = [spec.x] + ([spec.color] if spec.color and spec.color != spec.x else [])
        d = d.groupby(keys, as_index=False, dropna=False)[spec.y].agg(spec.agg)
    if t in {"bar", "pie"} and spec.top_n and spec.y:
        d = d.nlargest(spec.top_n, spec.y)
    if t in {"line", "area"} and spec.x:
        d = d.sort_values(spec.x)
    if t == "scatter" and len(d) > 5000:
        d = d.sample(5000, random_state=0)
    kw: dict[str, Any] = {"title": spec.title or None}
    if t == "bar": fig = px.bar(d, x=spec.x, y=spec.y, color=spec.color, **kw)
    elif t == "line": fig = px.line(d, x=spec.x, y=spec.y, color=spec.color, markers=True, **kw)
    elif t == "area": fig = px.area(d, x=spec.x, y=spec.y, color=spec.color, **kw)
    elif t == "scatter": fig = px.scatter(d, x=spec.x, y=spec.y, color=spec.color, **kw)
    elif t == "histogram": fig = px.histogram(d, x=spec.x, color=spec.color, **kw)
    elif t == "box": fig = px.box(d, x=spec.x, y=spec.y, color=spec.color, **kw)
    elif t == "pie": fig = px.pie(d, names=spec.x, values=spec.y, **kw)
    else:  # heatmap
        if spec.x and spec.y and spec.color:
            pv = d.pivot_table(index=spec.y, columns=spec.x, values=spec.color, aggfunc="mean")
            fig = px.imshow(pv, aspect="auto", color_continuous_scale="Blues", **kw)
        else:
            corr = d.select_dtypes("number").corr()
            fig = px.imshow(corr, text_auto=".2f", zmin=-1, zmax=1, color_continuous_scale="RdBu_r", **kw)
    fig.update_layout(template="plotly_white", margin=dict(l=40, r=20, t=60, b=40))
    return fig


def figure_to_dict(fig: go.Figure) -> dict[str, Any]:
    return json.loads(fig.to_json())


def default_charts(df: pd.DataFrame) -> list[ChartSpec]:
    """Deterministic fallback when the LLM suggests nothing valid."""
    d = prepare_frame(df)
    sem = {c: classify_column(d[c], str(c)) for c in d.columns}
    num = [c for c in d.columns if sem[c] == "numeric"]
    cat = [c for c in d.columns if sem[c] == "categorical"]
    dt = [c for c in d.columns if sem[c] == "datetime"]
    out: list[ChartSpec] = []
    if dt and num:
        out.append(ChartSpec(chart_type="line", x=dt[0], y=num[0], title=f"{num[0]} over time"))
    if cat and num:
        out.append(ChartSpec(chart_type="bar", x=cat[0], y=num[0], top_n=15, title=f"{num[0]} by {cat[0]}"))
    if not out and len(num) >= 2:
        out.append(ChartSpec(chart_type="scatter", x=num[0], y=num[1], title=f"{num[1]} vs {num[0]}"))
    if not out and num:
        out.append(ChartSpec(chart_type="histogram", x=num[0], title=f"Distribution of {num[0]}"))
    return out[:2]
