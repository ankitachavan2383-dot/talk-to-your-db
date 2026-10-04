"""Dataset profiling: types, missing values, duplicates, stats, correlations, trends, outliers, KPIs, quality."""
from __future__ import annotations

import re
import warnings
from typing import Any

import numpy as np
import pandas as pd

from app.analysis.models import ColumnProfile, DatasetProfile, KPI, QualityIssue
from app.analysis.stats import correlation_pairs, outlier_info, trend_for
from app.core.serialization import sanitize

METRIC_HINT = re.compile(r"(revenue|sales|amount|total|profit|cost|price|spend|income|quantity|qty|units|margin|value|count)", re.I)
MEAN_HINT = re.compile(r"(price|rate|margin|pct|percent|ratio|score|age|unit_)", re.I)
NONNEG_HINT = re.compile(r"(quantity|qty|price|amount|revenue|sales|units|age|count)", re.I)
ID_HINT = re.compile(r"(^id$|_id$|^id_|uuid|guid)", re.I)
DATE_LIKE = re.compile(r"^\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})")


def _try_datetime(s: pd.Series) -> pd.Series | None:
    sample = s.dropna().astype(str).head(200)
    if len(sample) < 3 or sample.str.match(DATE_LIKE).mean() < 0.8:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(s, errors="coerce", format="mixed")
    return parsed if parsed.notna().sum() >= 0.9 * s.notna().sum() else None


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Analysis view of the data (datetime-like text parsed). The caller's frame is never modified."""
    out = df.copy(deep=False)
    for c in df.columns:
        if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
            conv = _try_datetime(df[c])
            if conv is not None:
                out[c] = conv
    return out


def _nunique(s: pd.Series) -> int:
    try:
        return int(s.nunique(dropna=True))
    except TypeError:  # unhashable cells (lists/dicts from JSON)
        return int(s.astype(str).nunique())


def classify_column(s: pd.Series, name: str) -> str:
    n = len(s)
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    u = _nunique(s)
    if pd.api.types.is_numeric_dtype(s):
        if ID_HINT.search(name) and n and u / n > 0.9:
            return "id"
        return "numeric"
    if ID_HINT.search(name) and n and u / n > 0.9:
        return "id"
    return "categorical" if u <= max(20, 0.05 * n) else "text"


def _column_profile(s: pd.Series, name: str, sem: str, n: int) -> ColumnProfile:
    missing = int(s.isna().sum())
    stats: dict[str, Any] = {}
    top: list[dict[str, Any]] = []
    if sem in ("numeric", "id") and pd.api.types.is_numeric_dtype(s):
        d = s.dropna().astype(float)
        if len(d):
            stats = {"min": d.min(), "max": d.max(), "mean": d.mean(), "median": d.median(), "std": d.std() if len(d) > 1 else 0.0,
                     "q25": d.quantile(.25), "q75": d.quantile(.75), "skew": d.skew() if len(d) > 2 else 0.0, "sum": d.sum()}
    elif sem == "datetime":
        d = s.dropna()
        if len(d):
            stats = {"min": d.min(), "max": d.max(), "span_days": (d.max() - d.min()).days}
    else:
        try:
            vc = s.astype(str).value_counts().head(5)
            top = [{"value": k, "count": int(v)} for k, v in vc.items()]
        except Exception:
            pass
        if sem == "text":
            stats = {"avg_len": float(s.dropna().astype(str).str.len().mean()) if n - missing else 0.0}
    return ColumnProfile(name=name, dtype=str(s.dtype), semantic=sem, non_null=n - missing, missing=missing,
                         missing_pct=round(100 * missing / n, 2) if n else 0.0, unique=_nunique(s),
                         stats=sanitize(stats), top_values=top)


def _quality(d: pd.DataFrame, sem: dict[str, str], cols: list[ColumnProfile], dup_pct: float, outliers: list) -> list[QualityIssue]:
    q: list[QualityIssue] = []
    if dup_pct > 0:
        q.append(QualityIssue(severity="medium" if dup_pct > 1 else "low", column=None, issue="Duplicate rows",
                              detail=f"{dup_pct:.2f}% of rows are exact duplicates."))
    for c in cols:
        if c.missing_pct > 5:
            sev = "high" if c.missing_pct > 50 else "medium" if c.missing_pct > 20 else "low"
            q.append(QualityIssue(severity=sev, column=c.name, issue="Missing values", detail=f"{c.missing_pct:.1f}% missing ({c.missing} rows)."))
        if c.unique <= 1 and c.non_null > 1:
            q.append(QualityIssue(severity="low", column=c.name, issue="Constant column", detail="Only one distinct value."))
        s = d[c.name]
        if s.dtype == object:
            sample = s.dropna().head(1000)
            if len(sample):
                if len({type(v).__name__ for v in sample}) > 1:
                    q.append(QualityIssue(severity="medium", column=c.name, issue="Mixed types", detail="Column mixes several Python types."))
                strs = sample[sample.map(lambda v: isinstance(v, str))]
                if len(strs):
                    if pd.to_numeric(strs, errors="coerce").notna().mean() > 0.95:
                        q.append(QualityIssue(severity="medium", column=c.name, issue="Numeric stored as text", detail="Values look numeric but are strings."))
                    if (strs != strs.str.strip()).any():
                        q.append(QualityIssue(severity="low", column=c.name, issue="Leading/trailing whitespace", detail="Some values have extra spaces."))
                    if c.semantic == "categorical" and strs.str.lower().str.strip().nunique() < strs.nunique():
                        q.append(QualityIssue(severity="medium", column=c.name, issue="Inconsistent categories", detail="Same label appears with different casing/spacing."))
        if c.semantic == "numeric" and NONNEG_HINT.search(c.name) and c.stats.get("min") is not None and c.stats["min"] < 0:
            q.append(QualityIssue(severity="medium", column=c.name, issue="Unexpected negative values", detail=f"Minimum is {c.stats['min']:.4g}."))
    for o in outliers:
        if o.pct >= 1:
            q.append(QualityIssue(severity="medium" if o.pct > 5 else "low", column=o.column, issue="Outliers (IQR rule)", detail=f"{o.count} values ({o.pct}%) outside [{o.lower:.4g}, {o.upper:.4g}]."))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(q, key=lambda i: order[i.severity])


def profile_dataframe(df: pd.DataFrame) -> DatasetProfile:
    d = prepare_frame(df)
    n = len(d)
    sem = {c: classify_column(d[c], str(c)) for c in d.columns}
    cols = [_column_profile(d[c], str(c), sem[c], n) for c in d.columns]

    try:
        dup = int(d.duplicated().sum())
    except TypeError:
        dup = int(d.astype(str).duplicated().sum())
    dup_pct = round(100 * dup / n, 2) if n else 0.0

    numeric = [c for c in d.columns if sem[c] == "numeric"]
    sample = d if n <= 200_000 else d.sample(200_000, random_state=0)
    corr = correlation_pairs(sample, numeric[:60])
    outliers = [o for c in numeric[:40] if (o := outlier_info(c, d[c]))]

    dates = [c for c in d.columns if sem[c] == "datetime"]
    metrics = [c for c in numeric if METRIC_HINT.search(c)] or numeric
    trends = []
    if dates:
        for m in metrics[:3]:
            agg = "mean" if MEAN_HINT.search(m) else "sum"
            t = trend_for(d, dates[0], m, agg)
            if t:
                trends.append(t)

    kpis = [KPI(name="rows", label="Rows", value=n)]
    for m in metrics[:4]:
        s = d[m].dropna()
        if s.empty:
            continue
        use_mean = bool(MEAN_HINT.search(m))
        t = next((t for t in trends if t.metric == m and not t.last_period_partial), None)
        kpis.append(KPI(name=m, label=f"{'Avg' if use_mean else 'Total'} {m}", value=float(s.mean() if use_mean else s.sum()),
                        delta_pct=t.pct_change if t else None))
    if dates and d[dates[0]].notna().any():
        kpis.append(KPI(name="date_range", label="Date range", value=f"{d[dates[0]].min():%Y-%m-%d} → {d[dates[0]].max():%Y-%m-%d}"))

    return DatasetProfile(
        rows=n, cols=d.shape[1], memory_mb=round(float(df.memory_usage(deep=True).sum()) / 1e6, 3),
        duplicate_rows=dup, duplicate_pct=dup_pct, columns=cols, correlations=corr, outliers=outliers,
        trends=trends, kpis=kpis, quality=_quality(d, sem, cols, dup_pct, outliers),
    )


def compact_profile(p: DatasetProfile) -> dict[str, Any]:
    """Small, LLM-friendly summary of a profile (facts the model may cite)."""
    return sanitize({
        "rows": p.rows, "duplicate_rows": p.duplicate_rows,
        "columns": [{"name": c.name, "type": c.semantic, "missing_pct": c.missing_pct,
                     **({k: c.stats[k] for k in ("min", "max", "mean", "sum") if k in c.stats})} for c in p.columns[:40]],
        "kpis": [k.model_dump() for k in p.kpis],
        "trends": [{**t.model_dump(exclude={"series"}), "series": t.series[-12:]} for t in p.trends],
        "correlations": [c.model_dump() for c in p.correlations[:5]],
        "outliers": [o.model_dump() for o in p.outliers[:5]],
        "quality": [q.model_dump() for q in p.quality[:8]],
    })
