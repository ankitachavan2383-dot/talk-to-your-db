"""SQL safety gate. Everything the LLM writes passes through here before it can touch a database.

Layers (defence in depth - this is layer 1 of 4):
  1. SQLGlot: single statement, SELECT-only AST, no DML/DDL/locks/INTO, denied functions,
     system schemas blocked, table allow-list from the inspected schema, LIMIT enforced.
  2. Executor: READ ONLY transaction + statement timeout + hard row cap.
  3. Connection role check: refuse superuser / DDL-capable accounts.
  4. DB role itself is read-only (db/init/01_init.sql).
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.db.connectors import DialectAdapter


class SQLValidationError(ValueError):
    pass


def _nodes(*names: str) -> tuple[type, ...]:
    return tuple(c for c in (getattr(exp, n, None) for n in names) if isinstance(c, type))


FORBIDDEN = _nodes(
    "Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "AlterTable", "TruncateTable", "Command",
    "Into", "Lock", "Set", "Use", "Copy", "Grant", "Revoke", "Transaction", "Commit", "Rollback", "Pragma",
    "LoadData", "Analyze", "Describe", "Show", "Kill", "Execute", "Declare",
)
QUERY_ROOTS = _nodes("Select", "Union", "Intersect", "Except", "Subquery")
GENERIC_DENIED_FUNCS = frozenset({"sleep", "pg_sleep", "benchmark", "load_file", "sys_exec", "sys_eval", "xp_cmdshell"})


@dataclass(frozen=True)
class ValidatedSQL:
    sql: str
    tables: frozenset[str]


def _unwrap(node: exp.Expression) -> exp.Expression:
    while isinstance(node, exp.Subquery) and node.this is not None:
        node = node.this
    return node


def validate_sql(
    sql: str,
    adapter: DialectAdapter,
    allowed_tables: set[str],
    default_limit: int = 1000,
    max_rows: int = 10_000,
) -> ValidatedSQL:
    if not sql or not sql.strip():
        raise SQLValidationError("Empty SQL.")
    if len(sql) > 20_000:
        raise SQLValidationError("SQL too long.")

    try:
        statements = [s for s in sqlglot.parse(sql, read=adapter.sqlglot_dialect) if s is not None]
    except SqlglotError as exc:
        raise SQLValidationError(f"SQL could not be parsed: {str(exc)[:200]}") from exc
    if len(statements) != 1:
        raise SQLValidationError("Exactly one SQL statement is allowed.")

    tree = _unwrap(statements[0])
    if not isinstance(tree, QUERY_ROOTS):
        raise SQLValidationError("Only SELECT queries are allowed.")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN):
            raise SQLValidationError(f"Forbidden SQL construct: {type(node).__name__.upper()}.")
        if isinstance(node, exp.Func):
            fname = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if (fname in adapter.denied_functions or fname in GENERIC_DENIED_FUNCS
                    or fname.startswith(adapter.denied_function_prefixes)):
                raise SQLValidationError(f"Function '{fname}' is not allowed.")
    if tree.find(exp.Select) is None and not isinstance(tree, exp.Select):
        raise SQLValidationError("Query must contain a SELECT.")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    used: set[str] = set()
    for t in tree.find_all(exp.Table):
        if not t.name:
            continue  # table-valued function; functions are checked above
        name, schema = t.name.lower(), (t.db or "").lower()
        if not schema and name in cte_names:
            continue
        if schema in adapter.system_schemas:
            raise SQLValidationError(f"Access to system schema '{schema}' is not allowed.")
        qualified = f"{schema}.{name}" if schema else name
        if qualified not in allowed_tables:
            raise SQLValidationError(f"Table '{qualified}' does not exist or is not accessible.")
        used.add(qualified)

    # enforce row limit
    limit_node = tree.args.get("limit")
    if limit_node is None:
        tree = tree.limit(default_limit)
    else:
        try:
            n = int(limit_node.expression.name)
        except (ValueError, AttributeError):
            n = None
        if n is None or n > max_rows:
            tree = tree.limit(max_rows)

    return ValidatedSQL(sql=tree.sql(dialect=adapter.sqlglot_dialect), tables=frozenset(used))
