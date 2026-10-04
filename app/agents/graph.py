"""LangGraph assembly.

START -> router -+-> file_plan -> file_exec ------------------+
                 |                                            +-> analysis_engine -> viz_agent -> insight_agent -> persist -> END
                 +-> sql_schema -> sql_generate -> sql_validate -> sql_exec -+          (chart_request skips insight)
                 |                    ^________ retry loop ________|
                 +-> chart_from_last -> viz_agent
                 +-> dashboard_add | chitchat -> persist
   any failure -> fail -> persist
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.analysis_engine import make_analysis_engine
from app.agents.file_analyst import after_file_step, make_file_exec, make_file_plan
from app.agents.housekeeping import fail_node, make_chart_from_last, make_chitchat, make_dashboard_add, make_persist
from app.agents.insight_agent import make_insight_agent
from app.agents.router import make_router, route_after_router
from app.agents.sql_analyst import make_after_sql, make_sql_exec, make_sql_generate, make_sql_schema, make_sql_validate
from app.agents.state import AgentState
from app.agents.viz_agent import after_viz, make_viz_agent
from app.core.services import Services


def build_graph(svc: Services):
    g = StateGraph(AgentState)
    after_generate, after_validate, after_exec = make_after_sql(svc.settings.sql_max_retries)

    g.add_node("router", make_router(svc))
    g.add_node("file_plan", make_file_plan(svc))
    g.add_node("file_exec", make_file_exec(svc))
    g.add_node("sql_schema", make_sql_schema(svc))
    g.add_node("sql_generate", make_sql_generate(svc))
    g.add_node("sql_validate", make_sql_validate(svc))
    g.add_node("sql_exec", make_sql_exec(svc))
    g.add_node("chart_from_last", make_chart_from_last(svc))
    g.add_node("dashboard_add", make_dashboard_add(svc))
    g.add_node("chitchat", make_chitchat(svc))
    g.add_node("analysis_engine", make_analysis_engine())
    g.add_node("viz_agent", make_viz_agent(svc))
    g.add_node("insight_agent", make_insight_agent(svc))
    g.add_node("fail", fail_node)
    g.add_node("persist", make_persist(svc))

    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_after_router, {
        "file_plan": "file_plan", "sql_schema": "sql_schema", "chart_from_last": "chart_from_last",
        "dashboard_add": "dashboard_add", "chitchat": "chitchat"})

    # file analyst
    g.add_conditional_edges("file_plan", after_file_step, {"ok": "file_exec", "fail": "fail"})
    g.add_conditional_edges("file_exec", after_file_step, {"ok": "analysis_engine", "fail": "fail"})

    # sql analyst
    g.add_conditional_edges("sql_schema", lambda s: "fail" if s.get("error") else "ok", {"ok": "sql_generate", "fail": "fail"})
    g.add_conditional_edges("sql_generate", after_generate, {"validate": "sql_validate", "fail": "fail"})
    g.add_conditional_edges("sql_validate", after_validate, {"execute": "sql_exec", "retry": "sql_generate", "fail": "fail"})
    g.add_conditional_edges("sql_exec", after_exec, {"ok": "analysis_engine", "retry": "sql_generate", "fail": "fail"})

    # follow-up: chart previous result
    g.add_conditional_edges("chart_from_last", lambda s: "fail" if s.get("error") else "ok", {"ok": "viz_agent", "fail": "fail"})

    # shared tail
    g.add_edge("analysis_engine", "viz_agent")
    g.add_conditional_edges("viz_agent", after_viz, {"insight": "insight_agent", "persist": "persist"})
    g.add_edge("insight_agent", "persist")
    for n in ("dashboard_add", "chitchat", "fail"):
        g.add_edge(n, "persist")
    g.add_edge("persist", END)
    return g.compile()
