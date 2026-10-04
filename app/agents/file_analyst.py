"""File Analyst: LLM plans a structured QuerySpec; deterministic pandas code executes it."""
from __future__ import annotations

from app.agents import prompts
from app.agents.state import AgentState
from app.analysis.profiler import classify_column, prepare_frame
from app.analysis.query_engine import AnalysisError, check_spec, run_query
from app.core.services import Services
from app.llm.client import LLMError
from app.schemas import QuerySpec


def _columns_prompt(df, send_values: bool) -> str:
    lines = []
    for c in df.columns:
        sem = classify_column(df[c], str(c))
        line = f"- {c} | {sem} | {df[c].dtype}"
        if send_values and sem == "categorical":
            vals = [str(v) for v in df[c].dropna().unique()[:8]]
            line += f" | e.g. {vals}"
        lines.append(line)
    return "\n".join(lines)


def make_file_plan(svc: Services):
    def file_plan(state: AgentState) -> dict:
        df = prepare_frame(svc.dataset_frame(state["source_id"]))
        system = prompts.FILE_PLAN.format(columns=_columns_prompt(df, svc.settings.send_sample_values_to_llm))
        user, err = state["message"], None
        for _ in range(2):
            try:
                spec = svc.llm.structured(system, user, QuerySpec, history=state.get("history"))
                check_spec(df, spec)
                return {"source_df": df, "spec": spec, "error": None}
            except AnalysisError as exc:
                err = str(exc)
                user = f"{state['message']}\n\nYour previous plan was invalid: {err}. Fix it."
            except LLMError as exc:
                err = str(exc)
                break
        return {"source_df": df, "error": f"I couldn't build a valid analysis plan: {err}"}

    return file_plan


def make_file_exec(svc: Services):
    def file_exec(state: AgentState) -> dict:
        if state.get("error"):
            return {}
        try:
            res = run_query(state["source_df"], state["spec"])
        except AnalysisError as exc:
            return {"error": str(exc)}
        return {"result_df": res.df, "notes": res.notes, "facts": {"query_summary": res.summary} if res.summary else {}}

    return file_exec


def after_file_step(state: AgentState) -> str:
    return "fail" if state.get("error") else "ok"
