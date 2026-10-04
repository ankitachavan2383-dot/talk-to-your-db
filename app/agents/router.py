from __future__ import annotations

from app.agents import prompts
from app.agents.state import AgentState
from app.core.services import Services
from app.llm.client import LLMError
from app.schemas import IntentDecision


def make_router(svc: Services):
    def router(state: AgentState) -> dict:
        has_prev = svc.repo.last_run(state["session_id"], with_result=True) is not None
        hint = "" if has_prev else "\n(There is no previous result in this session yet.)"
        try:
            d = svc.llm.structured(prompts.ROUTER + hint, state["message"], IntentDecision, history=state.get("history"))
            intent = d.intent
        except LLMError:
            intent = "data_question"
        if intent in ("chart_request", "dashboard_add") and not has_prev:
            intent = "data_question"  # nothing to chart/add yet -> treat as a fresh question
        return {"intent": intent}

    return router


def route_after_router(state: AgentState) -> str:
    intent = state["intent"]
    if intent == "data_question":
        return "sql_schema" if state["source_type"] == "connection" else "file_plan"
    return {"chart_request": "chart_from_last", "dashboard_add": "dashboard_add", "chitchat": "chitchat"}[intent]
