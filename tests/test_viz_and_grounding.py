import pandas as pd
import pytest

from app.agents.insight_agent import unverified_numbers
from app.schemas import ChartSpec
from app.viz.chart_factory import ChartSpecError, build_figure, default_charts


def test_bar_chart_and_defaults(sales_df):
    fig = build_figure(sales_df, ChartSpec(chart_type="bar", x="product", y="revenue", agg="sum", title="t"))
    assert len(fig.data) == 1
    assert default_charts(sales_df)


def test_bad_chart_specs_rejected(sales_df):
    with pytest.raises(ChartSpecError):
        build_figure(sales_df, ChartSpec(chart_type="bar", x="ghost", y="revenue"))
    with pytest.raises(ChartSpecError):
        build_figure(sales_df, ChartSpec(chart_type="bar", x="region", y="product"))  # y not numeric


def test_number_grounding():
    facts = {"preview": [{"revenue": 12345.67}], "summary": {"pct_change": -18.4}}
    assert unverified_numbers("Revenue was 12,346, down 18.4%.", facts) == []
    assert unverified_numbers("Revenue was 99,999.", facts) == ["99,999"]
