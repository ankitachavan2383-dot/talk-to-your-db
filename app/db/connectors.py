"""Dialect adapters. Adding a database = one subclass + one registry entry."""
from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Engine


class UnsafeConnectionError(RuntimeError):
    pass


class DialectAdapter:
    name: str = ""
    sqlglot_dialect: str = ""
    drivername: str = ""
    system_schemas: frozenset[str] = frozenset()
    denied_functions: frozenset[str] = frozenset()
    denied_function_prefixes: tuple[str, ...] = ()

    def build_url(self, host: str, port: int, database: str, username: str, password: str) -> URL:
        return URL.create(self.drivername, username=username, password=password, host=host, port=port, database=database)

    def connect_args(self, timeout_s: int) -> dict[str, Any]:
        return {}

    def prepare(self, conn: Connection, timeout_s: int) -> None:
        """Run first in every query transaction: force read-only + timeout."""

    def assert_safe_role(self, conn: Connection) -> None:
        """Raise UnsafeConnectionError if the DB account can write / administer."""

    def make_engine(self, url: URL | str, timeout_s: int) -> Engine:
        return create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2, connect_args=self.connect_args(timeout_s))


class PostgresAdapter(DialectAdapter):
    name = "postgres"
    sqlglot_dialect = "postgres"
    drivername = "postgresql+psycopg"
    system_schemas = frozenset({"pg_catalog", "information_schema", "pg_toast"})
    denied_functions = frozenset({
        "pg_sleep", "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file", "set_config",
        "current_setting", "dblink", "dblink_exec", "lo_import", "lo_export", "pg_terminate_backend",
        "pg_cancel_backend", "pg_reload_conf", "txid_current", "query_to_xml", "xmlparse",
    })
    denied_function_prefixes = ("pg_", "lo_", "dblink")

    def connect_args(self, timeout_s: int) -> dict[str, Any]:
        opts = f"-c statement_timeout={timeout_s * 1000} -c default_transaction_read_only=on -c idle_in_transaction_session_timeout=30000"
        return {"options": opts}

    def prepare(self, conn: Connection, timeout_s: int) -> None:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_s) * 1000}"))

    def assert_safe_role(self, conn: Connection) -> None:
        row = conn.execute(text(
            "SELECT (rolsuper OR rolcreaterole OR rolcreatedb) AS powerful, "
            "has_schema_privilege(current_user, 'public', 'CREATE') AS can_create "
            "FROM pg_roles WHERE rolname = current_user"
        )).one()
        if row.powerful or row.can_create:
            raise UnsafeConnectionError(
                "This database account can create objects or is an admin role. "
                "Connect with a dedicated read-only user (see db/init/01_init.sql)."
            )


class MySQLAdapter(DialectAdapter):
    """Needs `pip install pymysql`. Included as the template for future dialects."""

    name = "mysql"
    sqlglot_dialect = "mysql"
    drivername = "mysql+pymysql"
    system_schemas = frozenset({"mysql", "information_schema", "performance_schema", "sys"})
    denied_functions = frozenset({"sleep", "benchmark", "load_file", "get_lock", "release_lock"})

    def prepare(self, conn: Connection, timeout_s: int) -> None:
        conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        conn.execute(text(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_s) * 1000}"))

    def assert_safe_role(self, conn: Connection) -> None:
        grants = " ".join(str(r[0]).upper() for r in conn.execute(text("SHOW GRANTS")))
        if any(w in grants for w in ("ALL PRIVILEGES", " INSERT", " UPDATE", " DELETE", " DROP", " CREATE", " ALTER")):
            raise UnsafeConnectionError("MySQL account has write privileges; use a SELECT-only user.")


ADAPTERS: dict[str, DialectAdapter] = {a.name: a for a in (PostgresAdapter(), MySQLAdapter())}


def get_adapter(dialect: str) -> DialectAdapter:
    try:
        return ADAPTERS[dialect]
    except KeyError:
        raise ValueError(f"Unsupported dialect '{dialect}'. Supported: {', '.join(ADAPTERS)}") from None


def test_connection(engine: Engine, adapter: DialectAdapter, require_readonly: bool) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        if require_readonly:
            adapter.assert_safe_role(conn)
        conn.rollback()
