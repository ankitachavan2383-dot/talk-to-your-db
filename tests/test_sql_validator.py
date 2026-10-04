import pytest

from app.db.connectors import PostgresAdapter
from app.sql.validator import SQLValidationError, validate_sql

A = PostgresAdapter()
ALLOWED = {"orders", "public.orders", "products", "public.products"}


def ok(sql, **kw):
    return validate_sql(sql, A, ALLOWED, **kw)


def test_simple_select_gets_limit():
    v = ok("SELECT product_id, SUM(quantity) FROM orders GROUP BY 1")
    assert "LIMIT 1000" in v.sql.upper() and v.tables == {"orders"}


def test_existing_limit_is_capped():
    assert "LIMIT 50" in ok("SELECT * FROM orders LIMIT 50", max_rows=100).sql.upper()
    assert "LIMIT 100" in ok("SELECT * FROM orders LIMIT 999999", max_rows=100).sql.upper()


def test_cte_and_join_ok():
    ok("WITH t AS (SELECT * FROM orders) SELECT p.name FROM t JOIN public.products p ON p.product_id = t.product_id")


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "UPDATE orders SET quantity = 0",
    "INSERT INTO orders VALUES (1)",
    "DROP TABLE orders",
    "TRUNCATE orders",
    "CREATE TABLE x AS SELECT 1",
    "ALTER TABLE orders ADD COLUMN x int",
    "SELECT * INTO newtable FROM orders",
    "SELECT * FROM orders; DROP TABLE orders",
    "SELECT * FROM orders FOR UPDATE",
    "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    "SELECT pg_sleep(100)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM secrets",
    "COPY orders TO '/tmp/x'",
    "SET ROLE postgres",
    "VACUUM",
    "",
])
def test_rejects_dangerous_or_unknown(sql):
    with pytest.raises(SQLValidationError):
        ok(sql)


def test_unparseable_sql_rejected():
    with pytest.raises(SQLValidationError):
        ok("SELEC FROM WHERE ((")
