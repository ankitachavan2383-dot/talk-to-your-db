from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    semantic: str  # numeric | categorical | datetime | boolean | text | id
    non_null: int
    missing: int
    missing_pct: float
    unique: int
    stats: dict[str, Any] = Field(default_factory=dict)
    top_values: list[dict[str, Any]] = Field(default_factory=list)


class OutlierInfo(BaseModel):
    column: str
    count: int
    pct: float
    lower: float
    upper: float


class CorrelationPair(BaseModel):
    a: str
    b: str
    r: float


class TrendInfo(BaseModel):
    metric: str
    date_col: str
    freq: str
    periods: int
    slope_per_period: float
    direction: Literal["up", "down", "flat"]
    last_period: str
    last_period_partial: bool
    last_value: float
    previous_value: float
    pct_change: float | None
    series: list[dict[str, Any]] = Field(default_factory=list)


class KPI(BaseModel):
    name: str
    label: str
    value: float | int | str
    delta_pct: float | None = None


class QualityIssue(BaseModel):
    severity: Literal["high", "medium", "low"]
    column: str | None
    issue: str
    detail: str


class DatasetProfile(BaseModel):
    rows: int
    cols: int
    memory_mb: float
    duplicate_rows: int
    duplicate_pct: float
    columns: list[ColumnProfile]
    correlations: list[CorrelationPair] = Field(default_factory=list)
    outliers: list[OutlierInfo] = Field(default_factory=list)
    trends: list[TrendInfo] = Field(default_factory=list)
    kpis: list[KPI] = Field(default_factory=list)
    quality: list[QualityIssue] = Field(default_factory=list)
