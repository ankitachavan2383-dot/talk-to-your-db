"""Deterministic statistics. Every number the user sees is computed here, never by the LLM."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.models import CorrelationPair, OutlierInfo, TrendInfo


def choose_freq(dates: pd.Series) -> str:
    span = (dates.max() - dates.min()).days
    if span <= 45:
        return "D"
    if span <= 180:
        return "W"
    if span <= 1100:
        return "M"
    return "Q"


def period_series(df: pd.DataFrame, date_col: str, metric: str, agg: str = "sum", freq: str | None = None) -> pd.Series:
    d = df[[date_col, metric]].dropna()
    if d.empty:
        return pd.Series(dtype=float)
    freq = freq or choose_freq(d[date_col])
    return d.groupby(d[date_col].dt.to_period(freq))[metric].agg(agg).sort_index()


def correlation_pairs(df: pd.DataFrame, cols: list[str], min_abs: float = 0.5, top: int = 10) -> list[CorrelationPair]:
    if len(cols) < 2:
        return []
    corr = df[cols].corr(numeric_only=True)
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            r = corr.loc[a, b]
            if pd.notna(r) and abs(r) >= min_abs:
                pairs.append(CorrelationPair(a=a, b=b, r=round(float(r), 4)))
    return sorted(pairs, key=lambda p: -abs(p.r))[:top]


def iqr_bounds(s: pd.Series, k: float = 1.5) -> tuple[float, float] | None:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if len(s) < 8:
        return None
    q1, q3 = s.quantile(0.25), s.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return None
    return float(q1 - k * iqr), float(q3 + k * iqr)


def outlier_info(name: str, s: pd.Series) -> OutlierInfo | None:
    b = iqr_bounds(s)
    if not b:
        return None
    s = pd.to_numeric(s, errors="coerce").dropna()
    count = int(((s < b[0]) | (s > b[1])).sum())
    if count == 0:
        return None
    return OutlierInfo(column=name, count=count, pct=round(100 * count / len(s), 2), lower=b[0], upper=b[1])


def trend_for(df: pd.DataFrame, date_col: str, metric: str, agg: str = "sum", max_points: int = 60) -> TrendInfo | None:
    d = df[[date_col, metric]].dropna()
    if len(d) < 3:
        return None
    freq = choose_freq(d[date_col])
    s = period_series(d, date_col, metric, agg, freq)
    if len(s) < 3:
        return None
    y = s.values.astype(float)
    slope = float(np.polyfit(np.arange(len(y)), y, 1)[0])
    rel = slope / (abs(y.mean()) or 1.0)
    direction = "up" if rel > 0.02 else "down" if rel < -0.02 else "flat"
    last, prev = float(y[-1]), float(y[-2])
    pct = round((last - prev) / abs(prev) * 100, 2) if prev else None
    partial = bool(d[date_col].max().normalize() < s.index[-1].end_time.normalize())
    return TrendInfo(
        metric=metric, date_col=date_col, freq=freq, periods=len(s), slope_per_period=round(slope, 4),
        direction=direction, last_period=str(s.index[-1]), last_period_partial=partial,
        last_value=last, previous_value=prev, pct_change=pct,
        series=[{"period": str(p), "value": float(v)} for p, v in list(s.items())[-max_points:]],
    )
