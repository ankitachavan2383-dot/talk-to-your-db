from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.deps import get_svc
from app.core.services import Services
from app.reports.context import build_context
from app.reports.excel_report import render_excel
from app.reports.html_report import render_html
from app.reports.pdf_report import render_pdf

router = APIRouter(prefix="/reports", tags=["reports"])

RENDERERS = {
    "html": (lambda c: render_html(c).encode(), "text/html", "html"),
    "pdf": (render_pdf, "application/pdf", "pdf"),
    "xlsx": (render_excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
}


@router.get("/{fmt}")
def download(fmt: str, source_type: str, source_id: int, svc: Services = Depends(get_svc)):
    if fmt not in RENDERERS:
        raise HTTPException(400, f"Format must be one of {', '.join(RENDERERS)}")
    try:
        ctx = build_context(svc, source_type, source_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    render, mime, ext = RENDERERS[fmt]
    return Response(render(ctx), media_type=mime, headers={"Content-Disposition": f'attachment; filename="report.{ext}"'})
