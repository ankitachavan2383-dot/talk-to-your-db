"""'Why did X change?' - period-over-period decomposition by dimension, computed in pandas."""
from __future__ import annotations

from typing import Any

import pandas as pd


def explain_change(df: pd.DataFrame, metric: str, date_col: str, dims: list[str], freq: str = "M",
                   agg: str = "sum", top: int = 10) -> tuple[pd.DataFrame, dict[str, Any]]:
    d = df[[date_col, metric, *dims]].dropna(subset=[date_col, metric]).copy()
    d["_p"] = d[date_col].dt.to_period(freq)
    periods = sorted(d["_p"].unique())
    if len(periods) < 2:
        raise ValueError("Need at least two time periods to explain a change.")
    prev_p, cur_p = periods[-2], periods[-1]
    cur, prev = d[d["_p"] == cur_p], d[d["_p"] == prev_p]
    total_cur, total_prev = float(cur[metric].agg(agg)), float(prev[metric].agg(agg))
    delta = total_cur - total_prev
    summary: dict[str, Any] = {
        "metric": metric, "agg": agg, "previous_period": str(prev_p), "current_period": str(cur_p),
        "previous_total": total_prev, "current_total": total_cur, "delta": delta,
        "pct_change": round(delta / abs(total_prev) * 100, 2) if total_prev else None,
        "current_period_partial": bool(d[date_col].max().normalize() < cur_p.end_time.normalize()),
    }
    rows = []
    for dim in dims:
        c = cur.groupby(dim, dropna=False)[metric].agg(agg)
        p = prev.groupby(dim, dropna=False)[metric].agg(agg)
        both = pd.concat([p.rename("previous"), c.rename("current")], axis=1).fillna(0.0)
        both["delta"] = both["current"] - both["previous"]
        both["share_of_change_pct"] = (both["delta"] / delta * 100) if delta else float("nan")
        for member, r in both.iterrows():
            rows.append({"dimension": dim, "member": str(member), "previous": r["previous"], "current": r["current"],
                         "delta": r["delta"], "share_of_change_pct": r["share_of_change_pct"]})
    out = pd.DataFrame(rows)
    if out.empty:
        return out, summary
    out = out.reindex(out["delta"].abs().sort_values(ascending=False).index).head(top).reset_index(drop=True)
    return out, summary
