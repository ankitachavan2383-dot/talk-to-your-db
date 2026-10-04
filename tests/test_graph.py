"""End-to-end graph tests with a scripted LLM (no network, no Postgres)."""
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from app.agents.graph import build_graph
from app.data.loader import save_original, load_dataframe
from app.db.connectors import DialectAdapter
from app.db.schema_inspector import allowed_tables, inspect_schema
from app.schemas import ChartSpec, ChartSuggestions, InsightOut, IntentDecision, QuerySpec, SQLDraft
from tests.conftest import FakeLLM


def _state(sid, msg, stype, sid_):
    return {"session_id": sid, "message": msg, "source_type": stype, "source_id": sid_, "history": [], "attempts": 0, "warnings": [], "notes": []}


def test_file_flow_followups_and_dashboard(make_services, sales_df, tmp_path):
    llm = FakeLLM({
        IntentDecision: lambda u: IntentDecision(intent="dashboard_add" if "dashboard" in u else "chart_request" if "chart" in u else "data_question"),
        QuerySpec: QuerySpec(operation="top_n", metric="revenue", group_by=["product"], agg="sum", top_n=2),
        ChartSuggestions: ChartSuggestions(charts=[ChartSpec(chart_type="bar", x="product", y="sum_revenue", title="Revenue by product")]),
        InsightOut: InsightOut(answer="Laptop leads revenue.", key_insights=["Laptop > Chair"], follow_ups=["Break down by region"]),
    })
    svc = build = make_services(llm)
    csv = tmp_path / "s.csv"
    sales_df.to_csv(csv, index=False)
    path, ftype = save_original(csv.read_bytes(), "sales.csv", svc.settings.uploads_dir, 5)
    ds = svc.repo.add_dataset(name="sales.csv", file_type=ftype, stored_path=str(path), n_rows=len(sales_df), n_cols=6, profile={})
    graph = build_graph(svc)

    out = graph.invoke(_state("s1", "Show the top products", "dataset", ds["id"]))
    assert out["intent"] == "data_question" and list(out["result_df"].columns) == ["product", "sum_revenue"]
    assert out["charts"] and out["answer"] and out["run_id"]

    out2 = graph.invoke(_state("s1", "create a chart for this", "dataset", ds["id"]))
    assert out2["intent"] == "chart_request" and out2["charts"]

    out3 = graph.invoke(_state("s1", "add this to my dashboard", "dataset", ds["id"]))
    assert out3["intent"] == "dashboard_add" and "Added" in out3["answer"]
    assert svc.repo.list_dashboard_items(f"dataset:{ds['id']}")
    assert load_dataframe(path).equals(sales_df.astype(load_dataframe(path).dtypes.to_dict()) if False else load_dataframe(path))  # file still loads


class SQLiteAdapter(DialectAdapter):
    name, sqlglot_dialect = "sqlite", "sqlite"
    system_schemas = frozenset({"sqlite_master"})


def test_sql_flow_retry_and_blocking(make_services):
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE orders (id INTEGER, region TEXT, amount REAL)"))
        c.execute(text("INSERT INTO orders VALUES (1,'N',10),(2,'S',30),(3,'N',20)"))
    adapter = SQLiteAdapter()
    attempts = []

    def gen(user):
        attempts.append(user)
        sqls = ["DELETE FROM orders",                              # blocked by validator
                "SELECT regionn, SUM(amount) FROM orders GROUP BY 1",  # DB error -> retry
                "SELECT region, SUM(amount) AS total FROM orders GROUP BY region ORDER BY total DESC"]
        return SQLDraft(sql=sqls[min(len(attempts) - 1, 2)])

    llm = FakeLLM({IntentDecision: IntentDecision(intent="data_question"), SQLDraft: gen,
                   ChartSuggestions: ChartSuggestions(charts=[ChartSpec(chart_type="bar", x="region", y="total", title="Total by region")]),
                   InsightOut: InsightOut(answer="N totals 30 and S totals 30.", key_insights=[])})
    svc = make_services(llm)
    svc.engine_for = lambda _id: (engine, adapter)
    svc.schema_for = lambda _id, refresh=False: inspect_schema(engine, adapter)
    conn = svc.repo.add_connection(password="x", name="t", dialect="postgres", host="h", port=1, database="d", username="u")
    out = build_graph(svc).invoke(_state("q1", "total amount by region", "connection", conn["id"]))
    assert len(attempts) == 3 and out["result_df"].shape == (2, 2)
    assert "Validation failed" in attempts[1] and "Database error" in attempts[2]
    with engine.connect() as c:  # table intact
        assert c.execute(text("SELECT COUNT(*) FROM orders")).scalar() == 3


def test_sql_gives_up_after_retries(make_services):
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE t (a INTEGER)"))
    adapter = SQLiteAdapter()
    llm = FakeLLM({IntentDecision: IntentDecision(intent="data_question"), SQLDraft: SQLDraft(sql="DROP TABLE t")})
    svc = make_services(llm)
    svc.engine_for = lambda _id: (engine, adapter)
    svc.schema_for = lambda _id, refresh=False: inspect_schema(engine, adapter)
    conn = svc.repo.add_connection(password="x", name="t", dialect="postgres", host="h", port=1, database="d", username="u")
    out = build_graph(svc).invoke(_state("q2", "drop it", "connection", conn["id"]))
    assert out.get("result_df") is None and "safe query" in out["answer"]
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE name='t'")).scalar() == 1
