import pandas as pd
import pytest

from app.analysis.drivers import explain_change
from app.analysis.profiler import prepare_frame, profile_dataframe
from app.analysis.query_engine import AnalysisError, run_query
from app.schemas import Filter, QuerySpec


def test_profile_basics(sales_df):
    orig = sales_df.copy(deep=True)
    p = profile_dataframe(sales_df)
    assert p.rows == len(sales_df) and p.duplicate_rows >= 1
    sem = {c.name: c.semantic for c in p.columns}
    assert sem["order_date"] == "datetime" and sem["revenue"] == "numeric" and sem["region"] == "categorical"
    assert any(o.column == "revenue" for o in p.outliers)
    assert any(q.issue == "Missing values" or q.issue == "Duplicate rows" for q in p.quality)
    assert p.trends and p.trends[0].metric in ("revenue", "quantity", "order_id")
    pd.testing.assert_frame_equal(sales_df, orig)  # original untouched


def test_top_n(sales_df):
    df = prepare_frame(sales_df)
    r = run_query(df, QuerySpec(operation="top_n", metric="revenue", group_by=["product"], agg="sum", top_n=1))
    assert r.df.iloc[0]["product"] == "Laptop" and len(r.df) == 1


def test_filter_and_scalar(sales_df):
    df = prepare_frame(sales_df)
    r = run_query(df, QuerySpec(operation="aggregate", metric="quantity", agg="count", filters=[Filter(column="region", op="==", value="South")]))
    assert r.df.iloc[0, 0] == int(((df["region"] == "South") & df["quantity"].notna()).sum())


def test_unknown_column_rejected(sales_df):
    with pytest.raises(AnalysisError):
        run_query(prepare_frame(sales_df), QuerySpec(operation="aggregate", metric="nope"))


def test_drivers_finds_engineered_drop(sales_df):
    df = prepare_frame(sales_df)
    out, summary = explain_change(df, "revenue", "order_date", ["region", "product"], "M")
    assert summary["delta"] < 0 and summary["current_period"] == "2024-12"
    top = out.iloc[0]
    assert top["member"] in ("Laptop", "North") and top["delta"] < 0
