"""Pydantic contracts shared by the agents, the API and the UI."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Intent = Literal["data_question", "chart_request", "dashboard_add", "chitchat"]


class IntentDecision(BaseModel):
    intent: Intent
    rationale: str = ""


class Filter(BaseModel):
    column: str
    op: Literal["==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains", "is_null", "not_null"]
    value: Any = None


class QuerySpec(BaseModel):
    """Structured, whitelisted plan the LLM may request. Executed by pandas code we wrote -
    the LLM never produces executable code."""

    operation: Literal["describe", "select", "aggregate", "top_n", "trend", "drivers", "correlation", "outliers"]
    metric: str | None = None
    agg: Literal["sum", "mean", "median", "min", "max", "count", "nunique"] = "sum"
    group_by: list[str] = Field(default_factory=list)
    date_col: str | None = None
    freq: Literal["D", "W", "M", "Q", "Y"] = "M"
    dims: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=1000)
    ascending: bool = False
    reasoning: str = ""


class SQLDraft(BaseModel):
    answerable: bool = True
    clarification: str | None = None
    sql: str = ""
    reasoning: str = ""


class ChartSpec(BaseModel):
    chart_type: Literal["bar", "line", "area", "scatter", "histogram", "box", "pie", "heatmap"]
    x: str | None = None
    y: str | None = None
    color: str | None = None
    agg: Literal["sum", "mean", "median", "min", "max", "count", "nunique"] | None = None
    top_n: int | None = Field(default=None, ge=1, le=100)
    title: str = ""


class ChartSuggestions(BaseModel):
    charts: list[ChartSpec] = Field(default_factory=list, max_length=3)


class InsightOut(BaseModel):
    answer: str
    key_insights: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=4000)
    source_type: Literal["dataset", "connection"]
    source_id: int


class ChatResponse(BaseModel):
    answer: str
    intent: str | None = None
    sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    table: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    kpis: list[dict[str, Any]] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    run_id: int | None = None
    error: str | None = None


class ConnectionCreate(BaseModel):
    name: str
    dialect: Literal["postgres", "mysql"] = "postgres"
    host: str
    port: int = 5432
    database: str
    username: str
    password: str


class DashboardFromRun(BaseModel):
    source_type: Literal["dataset", "connection"]
    source_id: int
    run_id: int
