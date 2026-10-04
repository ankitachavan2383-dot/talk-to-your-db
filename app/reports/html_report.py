from __future__ import annotations

import html
import json

import plotly.graph_objects as go

from app.reports.context import ReportContext

CSS = """body{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#1f2937}
h1{border-bottom:3px solid #4f46e5;padding-bottom:.4rem}h2{margin-top:2rem;color:#4f46e5}
.kpis{display:flex;flex-wrap:wrap;gap:1rem}.kpi{background:#f5f3ff;border-radius:10px;padding:1rem 1.4rem;min-width:150px}
.kpi b{display:block;font-size:1.6rem}table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border:1px solid #e5e7eb;padding:.35rem .6rem;text-align:left}th{background:#f3f4f6}
.sev-high{color:#b91c1c;font-weight:600}.sev-medium{color:#b45309}.sev-low{color:#6b7280}
pre{background:#111827;color:#e5e7eb;padding:.8rem;border-radius:8px;overflow:auto}.card{margin:1.2rem 0}"""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _fmt(v) -> str:
    return f"{v:,.2f}" if isinstance(v, float) else _e(v)


def render_html(ctx: ReportContext) -> str:
    parts = [f"<h1>{_e(ctx.title)}</h1><p>Generated {_e(ctx.generated_at)}</p>"]
    p = ctx.profile
    if p:
        parts.append("<h2>Key metrics</h2><div class='kpis'>" + "".join(
            f"<div class='kpi'><span>{_e(k['label'])}</span><b>{_fmt(k['value'])}</b>"
            + (f"<small>{k['delta_pct']:+.1f}% vs previous period</small>" if k.get("delta_pct") is not None else "")
            + "</div>" for k in p["kpis"]) + "</div>")
        parts.append(f"<p>{p['rows']:,} rows × {p['cols']} columns · {p['duplicate_rows']:,} duplicate rows ({p['duplicate_pct']}%)</p>")
    if ctx.insights:
        parts.append("<h2>Insights</h2>")
        for i in ctx.insights:
            parts.append(f"<div class='card'><b>{_e(i['question'])}</b><p>{_e(i['insight'])}</p>"
                         + (f"<pre>{_e(i['sql'])}</pre>" if i.get("sql") else "") + "</div>")
    charts = [it for it in ctx.dashboard_items if it["kind"] == "chart"]
    if charts:
        parts.append("<h2>Dashboard</h2>")
        for n, it in enumerate(charts):
            fig = go.Figure(it["payload"]["figure"])
            parts.append(f"<div class='card'><h3>{_e(it['title'])}</h3>"
                         + fig.to_html(full_html=False, include_plotlyjs="cdn" if n == 0 else False) + "</div>")
    for it in ctx.dashboard_items:
        if it["kind"] == "table" and it["payload"].get("rows"):
            rows = it["payload"]["rows"][:25]
            cols = list(rows[0].keys())
            parts.append(f"<h3>{_e(it['title'])}</h3><table><tr>" + "".join(f"<th>{_e(c)}</th>" for c in cols) + "</tr>"
                         + "".join("<tr>" + "".join(f"<td>{_fmt(r.get(c))}</td>" for c in cols) + "</tr>" for r in rows) + "</table>")
    if p:
        if p["quality"]:
            parts.append("<h2>Data-quality issues</h2><table><tr><th>Severity</th><th>Column</th><th>Issue</th><th>Detail</th></tr>"
                         + "".join(f"<tr><td class='sev-{q['severity']}'>{_e(q['severity'])}</td><td>{_e(q['column'])}</td>"
                                   f"<td>{_e(q['issue'])}</td><td>{_e(q['detail'])}</td></tr>" for q in p["quality"]) + "</table>")
        parts.append("<h2>Columns</h2><table><tr><th>Name</th><th>Type</th><th>Missing %</th><th>Unique</th></tr>"
                     + "".join(f"<tr><td>{_e(c['name'])}</td><td>{_e(c['semantic'])}</td><td>{c['missing_pct']}</td><td>{c['unique']}</td></tr>"
                               for c in p["columns"]) + "</table>")
        if p["correlations"]:
            parts.append("<h2>Strong correlations</h2><table><tr><th>A</th><th>B</th><th>r</th></tr>"
                         + "".join(f"<tr><td>{_e(c['a'])}</td><td>{_e(c['b'])}</td><td>{c['r']}</td></tr>" for c in p["correlations"]) + "</table>")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(ctx.title)}</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
