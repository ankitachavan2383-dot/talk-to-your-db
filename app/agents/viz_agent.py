"""Visualization Agent: LLM proposes ChartSpecs (data), code validates + renders them with Plotly."""
from __future__ import annotations

from app.agents import prompts
from app.agents.state import AgentState
from app.analysis.profiler import classify_column, prepare_frame
from app.core.serialization import sanitize
from app.core.services import Services
from app.llm.client import LLMError
from app.schemas import ChartSpec, ChartSuggestions
from app.viz.chart_factory import ChartSpecError, build_figure, default_charts, figure_to_dict


def make_viz_agent(svc: Services):
    def viz_agent(state: AgentState) -> dict:
        df = prepare_frame(state["result_df"])
        if df.empty or (len(df) == 1 and state.get("intent") != "chart_request"):
            return {"charts": []}
        cols = "\n".join(f"- {c} | {classify_column(df[c], str(c))} | {df[c].dtype} | {df[c].nunique()}" for c in df.columns)
        instruction = f'The user asked: "{state["message"]}". Honour the requested chart type if any.' if state.get("chart_instruction") else ""
        n = 1 if state.get("chart_instruction") else 2
        try:
            specs = svc.llm.structured(prompts.VIZ.format(n=n, instruction=instruction, columns=cols, rows=len(df)),
                                       state["message"], ChartSuggestions).charts
        except LLMError:
            specs = []
        charts: list[dict] = []
        for spec in specs[:n]:
            try:
                charts.append({"title": spec.title, "spec": spec.model_dump(), "figure": sanitize(figure_to_dict(build_figure(df, spec)))})
            except (ChartSpecError, ValueError, KeyError, TypeError):
                continue
        if not charts:
            for spec in default_charts(df)[:n]:
                try:
                    charts.append({"title": spec.title, "spec": spec.model_dump(), "figure": sanitize(figure_to_dict(build_figure(df, spec)))})
                except (ChartSpecError, ValueError, KeyError, TypeError):
                    continue
        out: dict = {"charts": charts}
        if state.get("intent") == "chart_request":
            out["answer"] = "Here's the chart based on your previous result." if charts else "I couldn't find a sensible chart for that result."
        return out

    return viz_agent


def after_viz(state: AgentState) -> str:
    return "persist" if state.get("intent") == "chart_request" else "insight"
