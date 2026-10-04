"""Small utility nodes: load previous result, dashboard add, chitchat, failure, persistence."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.agents import prompts
from app.agents.state import AgentState
from app.core.serialization import df_to_records, sanitize
from app.core.services import Services
from app.db.metadata import scope_of
from app.llm.client import LLMError


def _save_result(svc: Services, df: pd.DataFrame) -> str:
    import uuid
    path = svc.settings.results_dir / f"{uuid.uuid4().hex}.parquet"
    try:
        df.to_parquet(path, index=False)
    except Exception:  # mixed-type object columns -> stringify and retry
        df.astype({c: "string" for c in df.columns if df[c].dtype == object}).to_parquet(path, index=False)
    return str(path)


def make_chart_from_last(svc: Services):
    def chart_from_last(state: AgentState) -> dict:
        run = svc.repo.last_run(state["session_id"], with_result=True)
        if not run or not Path(run["result_path"]).exists():
            return {"error": "There is no previous result to chart yet. Ask a data question first."}
        return {"result_df": pd.read_parquet(run["result_path"]), "result_path": run["result_path"], "sql": run.get("sql") or "",
                "facts": run.get("facts") or {}, "chart_instruction": state["message"], "notes": []}

    return chart_from_last


def make_dashboard_add(svc: Services):
    def dashboard_add(state: AgentState) -> dict:
        run = svc.repo.last_run(state["session_id"], with_result=True) or svc.repo.last_run(state["session_id"])
        if not run:
            return {"answer": "There's nothing to add yet - ask a question or request a chart first."}
        scope = scope_of(state["source_type"], state["source_id"])
        added = 0
        for ch in run.get("charts") or []:
            svc.repo.add_dashboard_item(scope, "chart", ch.get("title") or "Chart", {"figure": ch["figure"], "spec": ch["spec"], "question": run["question"]})
            added += 1
        if not added and run.get("kpis"):
            for k in run["kpis"][:4]:
                svc.repo.add_dashboard_item(scope, "kpi", k["label"], {"kpi": k})
                added += 1
        if not added and run.get("result_path") and Path(run["result_path"]).exists():
            df = pd.read_parquet(run["result_path"])
            svc.repo.add_dashboard_item(scope, "table", run["question"][:120], {"rows": df_to_records(df, 50), "question": run["question"]})
            added = 1
        return {"answer": f"Added {added} item(s) to your dashboard." if added else "That result has nothing I can pin to the dashboard.",
                "added_items": added} if added else {"answer": "That result has nothing I can pin to the dashboard."}

    return dashboard_add


def make_chitchat(svc: Services):
    def chitchat(state: AgentState) -> dict:
        try:
            ans = svc.llm.chat(prompts.CHITCHAT, state["message"], history=state.get("history"))
        except LLMError:
            ans = "I can analyse your data, answer questions with SQL, build charts and a dashboard, and export reports. What would you like to explore?"
        return {"answer": ans}

    return chitchat


def fail_node(state: AgentState) -> dict:
    msg = state.get("clarification") if state.get("answerable") is False else None
    msg = msg or state.get("error") or state.get("sql_error") or "I couldn't complete that request."
    if state.get("sql_error") and not state.get("error"):
        msg = f"I couldn't produce a valid, safe query for that. Last problem: {state['sql_error']}"
    return {"answer": msg, "error": state.get("error") or state.get("sql_error"), "charts": [], "kpis": []}


def make_persist(svc: Services):
    def persist(state: AgentState) -> dict:
        sid, st, sid_ = state["session_id"], state["source_type"], state["source_id"]
        run_id = None
        df = state.get("result_df")
        if df is not None and state.get("intent") in ("data_question", "chart_request") and not state.get("error"):
            path = state.get("result_path") or _save_result(svc, df)
            run = svc.repo.add_run(
                session_id=sid, source_type=st, source_id=sid_, question=state["message"], intent=state.get("intent"),
                sql=state.get("sql") or None, spec=sanitize(state["spec"].model_dump()) if state.get("spec") is not None else None,
                facts=state.get("facts"), charts=state.get("charts"), kpis=state.get("kpis"),
                insight=state.get("answer"), result_path=path)
            run_id = run["id"]
        svc.repo.add_message(sid, "user", state["message"], st, sid_)
        svc.repo.add_message(sid, "assistant", state.get("answer", ""), st, sid_)
        return {"run_id": run_id}

    return persist
