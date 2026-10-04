"""Analysis Engine node: deterministic facts about the result (profile, KPIs, drivers). No LLM."""
from __future__ import annotations

import re

import pandas as pd

from app.agents.state import AgentState
from app.analysis.drivers import explain_change
from app.analysis.profiler import classify_column, compact_profile, prepare_frame, profile_dataframe
from app.core.serialization import df_to_records, sanitize

WHY = re.compile(r"\b(why|driver|cause|reason|decreas|increas|drop|decline|fell|rise|grew)\w*", re.I)


def _kpis_from_df(df: pd.DataFrame, profile) -> list[dict]:
    if len(df) == 1:
        out = []
        for c in df.columns:
            v = df.iloc[0][c]
            if isinstance(v, (int, float)) or pd.api.types.is_number(v):
                out.append({"name": c, "label": str(c).replace("_", " ").title(), "value": v, "delta_pct": None})
        return sanitize(out[:6])
    return sanitize([k.model_dump() for k in profile.kpis[:5]]) if profile else []


def make_analysis_engine():
    def analysis_engine(state: AgentState) -> dict:
        df: pd.DataFrame = state["result_df"]
        prepared = prepare_frame(df)
        facts = dict(state.get("facts") or {})
        facts.update({"question": state["message"], "row_count": len(df), "columns": [str(c) for c in df.columns],
                      "preview": df_to_records(df, 20), "notes": state.get("notes", [])})
        if state.get("sql"):
            facts["sql"] = state["sql"]
        warnings = []
        if state.get("truncated"):
            warnings.append("Result was truncated by the row limit.")

        profile = None
        try:
            if len(df) > 1:
                profile = profile_dataframe(df)
                facts["profile"] = compact_profile(profile)
        except Exception:  # profiling must never break the answer
            warnings.append("Automatic profiling of the result was skipped.")

        # SQL results shaped like (date, metric, dimension) -> automatic period-over-period driver analysis
        if WHY.search(state["message"]) and "drivers" not in facts.get("query_summary", {}) and "drivers" not in facts:
            sem = {c: classify_column(prepared[c], str(c)) for c in prepared.columns}
            dates = [c for c, s in sem.items() if s == "datetime"]
            nums = [c for c, s in sem.items() if s == "numeric"]
            cats = [c for c, s in sem.items() if s == "categorical"]
            if dates and nums and cats:
                try:
                    drv, summ = explain_change(prepared, nums[0], dates[0], cats[:3], "M")
                    facts["drivers"] = {"summary": sanitize(summ), "top_contributors": df_to_records(drv, 10)}
                except Exception:
                    pass
        if state.get("spec") is not None and state["spec"].operation == "drivers":
            facts["drivers"] = {"summary": facts.pop("query_summary", {}), "top_contributors": df_to_records(df, 10)}

        return {"facts": sanitize(facts), "kpis": _kpis_from_df(df, profile), "warnings": warnings}

    return analysis_engine
