from __future__ import annotations

import io
from xml.sax.saxutils import escape

import plotly.graph_objects as go
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.reports.context import ReportContext


def _tbl(data: list[list[str]], widths=None) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ede9fe")), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                           ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def render_pdf(ctx: ReportContext) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=ctx.title)
    ss = getSampleStyleSheet()
    P = lambda text, style="BodyText": Paragraph(escape(str(text)), ss[style])  # noqa: E731
    story = [P(ctx.title, "Title"), P(f"Generated {ctx.generated_at}", "Italic"), Spacer(1, 10)]
    p = ctx.profile
    if p:
        story += [P("Key metrics", "Heading2"),
                  _tbl([["Metric", "Value", "Change vs previous"]] + [
                      [k["label"], f"{k['value']:,.2f}" if isinstance(k["value"], float) else str(k["value"]),
                       f"{k['delta_pct']:+.1f}%" if k.get("delta_pct") is not None else "-"] for k in p["kpis"]]),
                  Spacer(1, 6), P(f"{p['rows']:,} rows x {p['cols']} columns; {p['duplicate_rows']:,} duplicate rows ({p['duplicate_pct']}%).")]
    if ctx.insights:
        story.append(P("Insights", "Heading2"))
        for i in ctx.insights:
            story += [P(i["question"], "Heading4"), P(i["insight"])]
    charts = [it for it in ctx.dashboard_items if it["kind"] == "chart"]
    if charts:
        story.append(P("Dashboard", "Heading2"))
        for it in charts:
            story.append(P(it["title"], "Heading4"))
            try:  # static export needs kaleido; degrade gracefully if unavailable
                png = go.Figure(it["payload"]["figure"]).to_image(format="png", width=900, height=450, scale=1)
                story.append(Image(io.BytesIO(png), width=16 * cm, height=8 * cm))
            except Exception:
                story.append(P("(Chart image unavailable - see the HTML report for the interactive version.)", "Italic"))
    if p and p["quality"]:
        story += [P("Data-quality issues", "Heading2"),
                  _tbl([["Severity", "Column", "Issue", "Detail"]] + [[q["severity"], q["column"] or "-", q["issue"], q["detail"]] for q in p["quality"][:25]],
                       [2 * cm, 3 * cm, 4 * cm, 8 * cm])]
    doc.build(story)
    return buf.getvalue()
