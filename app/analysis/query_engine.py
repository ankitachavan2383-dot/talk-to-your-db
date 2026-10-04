"""Executes a validated QuerySpec with pandas. No eval/exec: the LLM picks from a fixed menu of operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.analysis.drivers import explain_change
from app.analysis.stats import iqr_bounds, period_series
from app.schemas import Filter, QuerySpec


class AnalysisError(ValueError):
    pass


@dataclass
class QueryResult:
    df: pd.DataFrame
    notes: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def _need(df: pd.DataFrame, cols: list[str | None]) -> None:
    missing = [c for c in cols if c and c not in df.columns]
    if missing:
        raise AnalysisError(f"Unknown column(s): {', '.join(missing)}. Available: {', '.join(map(str, df.columns))}")


def check_spec(df: pd.DataFrame, spec: QuerySpec) -> None:
    _need(df, [spec.metric, spec.date_col, *spec.group_by, *spec.dims, *spec.columns, *[f.column for f in spec.filters]])
    if spec.operation in ("trend", "drivers") and not (spec.metric and spec.date_col):
        raise AnalysisError(f"'{spec.operation}' needs metric and date_col.")
    if spec.operation in ("aggregate", "top_n", "outliers") and not spec.metric and spec.agg != "count":
        raise AnalysisError(f"'{spec.operation}' needs a metric.")


def apply_filters(df: pd.DataFrame, filters: list[Filter]) -> pd.DataFrame:
    for f in filters:
        s, v = df[f.column], f.value
        if pd.api.types.is_datetime64_any_dtype(s) and v is not None and f.op not in ("in", "not_in", "contains"):
            v = pd.to_datetime(v)
        if f.op == "==": m = s == v
        elif f.op == "!=": m = s != v
        elif f.op == ">": m = s > v
        elif f.op == ">=": m = s >= v
        elif f.op == "<": m = s < v
        elif f.op == "<=": m = s <= v
        elif f.op == "in": m = s.isin(v if isinstance(v, list) else [v])
        elif f.op == "not_in": m = ~s.isin(v if isinstance(v, list) else [v])
        elif f.op == "contains": m = s.astype(str).str.contains(str(v), case=False, regex=False)
        elif f.op == "is_null": m = s.isna()
        else: m = s.notna()
        df = df[m]
    return df


def run_query(df: pd.DataFrame, spec: QuerySpec) -> QueryResult:
    check_spec(df, spec)
    d = apply_filters(df, spec.filters)
    notes = [f"Applied {len(spec.filters)} filter(s): {len(d)} of {len(df)} rows remain."] if spec.filters else []
    if d.empty:
        raise AnalysisError("No rows match the requested filters.")
    op = spec.operation

    if op == "describe":
        return QueryResult(d.describe(include="all").T.reset_index(names="column"), notes)

    if op == "select":
        cols = spec.columns or list(d.columns)
        out = d[cols]
        if spec.metric:
            out = out.sort_values(spec.metric, ascending=spec.ascending)
        return QueryResult(out.head(spec.top_n if spec.top_n != 10 else 100).reset_index(drop=True), notes)

    if op in ("aggregate", "top_n"):
        name = f"{spec.agg}_{spec.metric}" if spec.metric else "count"
        if not spec.group_by:
            val = len(d) if (spec.agg == "count" and not spec.metric) else d[spec.metric].agg(spec.agg)
            return QueryResult(pd.DataFrame({name: [val]}), notes)
        g = d.groupby(spec.group_by, dropna=False)
        out = (g.size().reset_index(name=name) if (spec.agg == "count" and not spec.metric)
               else g[spec.metric].agg(spec.agg).reset_index(name=name))
        out = out.sort_values(name, ascending=spec.ascending).reset_index(drop=True)
        if op == "top_n" or spec.top_n != 10 or len(out) > 50:
            out = out.head(spec.top_n)
        return QueryResult(out, notes)

    if op == "trend":
        s = period_series(d, spec.date_col, spec.metric, spec.agg, spec.freq)
        out = pd.DataFrame({"period": s.index.to_timestamp(), f"{spec.agg}_{spec.metric}": s.values})
        return QueryResult(out, notes)

    if op == "drivers":
        dims = spec.dims or spec.group_by
        if not dims:
            raise AnalysisError("'drivers' needs at least one dimension in dims.")
        out, summary = explain_change(d, spec.metric, spec.date_col, dims, spec.freq, spec.agg, top=spec.top_n)
        if summary.get("current_period_partial"):
            notes.append("The latest period is incomplete, so the decline may be partly a partial-period effect.")
        return QueryResult(out, notes, summary)

    if op == "correlation":
        num = d.select_dtypes("number")
        if num.shape[1] < 2:
            raise AnalysisError("Need at least two numeric columns for correlation.")
        return QueryResult(num.corr().round(4).reset_index(names="column"), notes)

    if op == "outliers":
        b = iqr_bounds(d[spec.metric])
        if not b:
            raise AnalysisError(f"Cannot compute outliers for '{spec.metric}'.")
        m = (d[spec.metric] < b[0]) | (d[spec.metric] > b[1])
        notes.append(f"IQR bounds for {spec.metric}: [{b[0]:.4g}, {b[1]:.4g}]; {int(m.sum())} outlier row(s).")
        return QueryResult(d[m].head(spec.top_n if spec.top_n != 10 else 100).reset_index(drop=True), notes,
                           {"lower": b[0], "upper": b[1], "count": int(m.sum())})

    raise AnalysisError(f"Unsupported operation '{op}'.")
