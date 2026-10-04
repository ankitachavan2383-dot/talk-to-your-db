from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_graph, get_svc
from app.core.serialization import df_to_records, sanitize
from app.core.services import Services
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, svc: Services = Depends(get_svc), graph=Depends(get_graph)):
    exists = svc.repo.get_dataset(req.source_id) if req.source_type == "dataset" else svc.repo.get_connection(req.source_id)
    if not exists:
        raise HTTPException(404, f"{req.source_type} {req.source_id} not found")
    state = {"session_id": req.session_id, "message": req.message, "source_type": req.source_type, "source_id": req.source_id,
             "history": svc.repo.history(req.session_id, 6), "attempts": 0, "warnings": [], "notes": []}
    out = graph.invoke(state)
    df = out.get("result_df")
    return ChatResponse(
        answer=out.get("answer", ""), intent=out.get("intent"), sql=out.get("validated_sql") or out.get("sql") or None,
        columns=[str(c) for c in df.columns] if df is not None else [], table=df_to_records(df, 200) if df is not None else [],
        charts=sanitize(out.get("charts", [])), kpis=sanitize(out.get("kpis", [])), insights=out.get("insights", []),
        follow_ups=out.get("follow_ups", []), warnings=out.get("warnings", []), notes=out.get("notes", []),
        run_id=out.get("run_id"), error=out.get("error"))


@router.get("/sessions/{session_id}/history")
def history(session_id: str, svc: Services = Depends(get_svc)):
    return svc.repo.history(session_id, 100)
