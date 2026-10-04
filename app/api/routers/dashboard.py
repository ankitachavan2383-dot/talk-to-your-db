from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_svc
from app.core.serialization import sanitize
from app.core.services import Services
from app.db.metadata import scope_of
from app.schemas import DashboardFromRun

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(source_type: str, source_id: int, svc: Services = Depends(get_svc)):
    return sanitize(svc.repo.list_dashboard_items(scope_of(source_type, source_id)))


@router.post("/from-run")
def add_from_run(body: DashboardFromRun, svc: Services = Depends(get_svc)):
    run = svc.repo.get_run(body.run_id)
    if not run or (run["source_type"], run["source_id"]) != (body.source_type, body.source_id):
        raise HTTPException(404, "Run not found for this source")
    scope, added = scope_of(body.source_type, body.source_id), 0
    for ch in run.get("charts") or []:
        svc.repo.add_dashboard_item(scope, "chart", ch.get("title") or "Chart", {"figure": ch["figure"], "spec": ch["spec"], "question": run["question"]})
        added += 1
    for k in (run.get("kpis") or [])[:4] if not added else []:
        svc.repo.add_dashboard_item(scope, "kpi", k["label"], {"kpi": k})
        added += 1
    return {"added": added}


@router.delete("/items/{item_id}")
def delete_item(item_id: int, svc: Services = Depends(get_svc)):
    svc.repo.delete_dashboard_item(item_id)
    return {"ok": True}
