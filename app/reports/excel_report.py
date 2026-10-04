from __future__ import annotations

import io

import pandas as pd

from app.reports.context import ReportContext


def _safe(df: pd.DataFrame) -> pd.DataFrame:
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v)
    return df


def render_excel(ctx: ReportContext) -> bytes:
    buf = io.BytesIO()
    p = ctx.profile or {}
    sheets: dict[str, pd.DataFrame] = {
        "Summary": pd.DataFrame({"Item": ["Report", "Generated", "Rows", "Columns", "Duplicate rows"],
                                 "Value": [ctx.title, ctx.generated_at, p.get("rows", ""), p.get("cols", ""), p.get("duplicate_rows", "")]}),
    }
    if p:
        sheets["KPIs"] = pd.DataFrame(p["kpis"])
        sheets["Columns"] = pd.DataFrame([{k: v for k, v in c.items() if k not in ("stats", "top_values")} | {f"stat_{k}": v for k, v in c["stats"].items()} for c in p["columns"]])
        sheets["Quality"] = pd.DataFrame(p["quality"])
        sheets["Correlations"] = pd.DataFrame(p["correlations"])
        sheets["Outliers"] = pd.DataFrame(p["outliers"])
        sheets["Trends"] = pd.DataFrame([{k: v for k, v in t.items() if k != "series"} for t in p["trends"]])
    if ctx.insights:
        sheets["Insights"] = pd.DataFrame(ctx.insights)
    for n, it in enumerate([i for i in ctx.dashboard_items if i["kind"] == "table"][:5], 1):
        sheets[f"Table {n}"] = pd.DataFrame(it["payload"].get("rows", []))
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            if df.empty:
                continue
            _safe(df).to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(10, max(len(str(c.value or "")) for c in col[:50]) + 2))
    return buf.getvalue()
