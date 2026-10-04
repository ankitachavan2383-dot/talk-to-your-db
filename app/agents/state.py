from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # input
    session_id: str
    message: str
    source_type: str  # "dataset" | "connection"
    source_id: int
    history: list[dict]
    # routing
    intent: str
    # file analyst
    source_df: Any
    spec: Any
    # sql analyst
    dialect: str
    schema_text: str
    allowed_tables: list[str]
    sql: str
    validated_sql: str
    sql_reasoning: str
    sql_error: str | None
    answerable: bool
    clarification: str | None
    attempts: int
    truncated: bool
    # shared analysis output
    result_df: Any
    result_path: str | None
    notes: list[str]
    facts: dict
    kpis: list[dict]
    charts: list[dict]
    chart_instruction: str | None
    # final
    answer: str
    insights: list[str]
    follow_ups: list[str]
    warnings: list[str]
    run_id: int | None
    error: str | None
