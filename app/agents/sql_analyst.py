"""SQL Analyst: inspect schema -> generate SQL -> validate (SQLGlot) -> execute read-only -> retry on error."""
from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.agents import prompts
from app.agents.state import AgentState
from app.core.services import Services
from app.db.schema_inspector import allowed_tables, schema_to_prompt
from app.llm.client import LLMError
from app.schemas import SQLDraft
from app.sql.executor import execute_readonly
from app.sql.validator import SQLValidationError, validate_sql


def make_sql_schema(svc: Services):
    def sql_schema(state: AgentState) -> dict:
        try:
            info = svc.schema_for(state["source_id"])
            _, adapter = svc.engine_for(state["source_id"])
        except Exception as exc:
            return {"error": f"Could not connect to the database: {exc.__class__.__name__}"}
        if not info["tables"]:
            return {"error": "No accessible tables were found for this connection."}
        return {"schema_text": schema_to_prompt(info), "allowed_tables": sorted(allowed_tables(info)),
                "dialect": adapter.name, "attempts": 0, "sql_error": None, "error": None}

    return sql_schema


def make_sql_generate(svc: Services):
    def sql_generate(state: AgentState) -> dict:
        system = prompts.SQL_GEN.format(dialect=state["dialect"], schema=state["schema_text"])
        user = f"Question: {state['message']}"
        if state.get("sql_error"):
            user += f"\n\nYour previous SQL:\n{state.get('sql')}\nFailed with: {state['sql_error']}\nReturn a corrected query."
        try:
            d = svc.llm.structured(system, user, SQLDraft, history=state.get("history"))
        except LLMError as exc:
            return {"error": str(exc), "answerable": True}
        return {"sql": d.sql, "sql_reasoning": d.reasoning, "answerable": d.answerable, "clarification": d.clarification}

    return sql_generate


def make_sql_validate(svc: Services):
    def sql_validate(state: AgentState) -> dict:
        _, adapter = svc.engine_for(state["source_id"])
        try:
            v = validate_sql(state["sql"], adapter, set(state["allowed_tables"]),
                             svc.settings.sql_default_limit, svc.settings.sql_max_rows)
        except SQLValidationError as exc:
            return {"sql_error": f"Validation failed: {exc}", "attempts": state.get("attempts", 0) + 1}
        return {"validated_sql": v.sql, "sql": v.sql, "sql_error": None}

    return sql_validate


def make_sql_exec(svc: Services):
    def sql_exec(state: AgentState) -> dict:
        engine, adapter = svc.engine_for(state["source_id"])
        try:
            ex = execute_readonly(engine, adapter, state["validated_sql"], svc.settings.sql_timeout_s, svc.settings.sql_max_rows)
        except SQLAlchemyError as exc:
            msg = str(getattr(exc, "orig", exc)).splitlines()[0][:300]
            return {"sql_error": f"Database error: {msg}", "attempts": state.get("attempts", 0) + 1}
        notes = [f"Query ran in {ex.elapsed_ms} ms and returned {len(ex.df)} row(s)."]
        if ex.truncated:
            notes.append(f"Result truncated to the first {svc.settings.sql_max_rows} rows.")
        return {"result_df": ex.df, "truncated": ex.truncated, "notes": notes, "sql_error": None}

    return sql_exec


def make_after_sql(max_retries: int):
    def after_generate(state: AgentState) -> str:
        if state.get("error") or not state.get("answerable", True):
            return "fail"
        return "validate"

    def after_validate(state: AgentState) -> str:
        if not state.get("sql_error"):
            return "execute"
        return "fail" if state.get("attempts", 0) > max_retries else "retry"

    def after_exec(state: AgentState) -> str:
        if not state.get("sql_error"):
            return "ok"
        return "fail" if state.get("attempts", 0) > max_retries else "retry"

    return after_generate, after_validate, after_exec
