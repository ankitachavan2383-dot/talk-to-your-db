from __future__ import annotations

import time
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.connectors import DialectAdapter


@dataclass
class Execution:
    df: pd.DataFrame
    truncated: bool
    elapsed_ms: int


def execute_readonly(engine: Engine, adapter: DialectAdapter, sql: str, timeout_s: int, max_rows: int) -> Execution:
    """Run an already-validated query inside a READ ONLY transaction with timeout and hard row cap."""
    start = time.perf_counter()
    with engine.connect() as conn:
        adapter.prepare(conn, timeout_s)  # must be the first statement of the transaction
        result = conn.execute(text(sql))
        rows = result.fetchmany(max_rows + 1)
        columns = list(result.keys())
        conn.rollback()  # never commit
    truncated = len(rows) > max_rows
    df = pd.DataFrame(rows[:max_rows], columns=columns)
    return Execution(df=df, truncated=truncated, elapsed_ms=int((time.perf_counter() - start) * 1000))
