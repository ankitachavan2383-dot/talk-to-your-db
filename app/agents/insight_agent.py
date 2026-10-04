"""Insight Agent: the LLM explains FACTS computed by Python. A grounding check flags unverifiable numbers."""
from __future__ import annotations

import json
import re

from app.agents import prompts
from app.agents.state import AgentState
from app.core.services import Services
from app.llm.client import LLMError
from app.schemas import InsightOut

NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _collect_numbers(obj, out: list[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(_parse(m) for m in NUM.findall(obj) if _parse(m) is not None)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_numbers(v, out)


def _parse(tok: str) -> float | None:
    try:
        return float(tok.replace(",", "").rstrip("."))
    except ValueError:
        return None


def unverified_numbers(text: str, facts: dict) -> list[str]:
    """Numbers in `text` that don't match (within rounding) any number in `facts`."""
    known: list[float] = []
    _collect_numbers(facts, known)
    known = [abs(k) for k in known]  # "down 18.4%" must match -18.4
    bad = []
    for tok in NUM.findall(text):
        v = _parse(tok)
        v = abs(v) if v is not None else None  # sign is conveyed in words ("down", "decline")
        if v is None or (abs(v) <= 10 and float(v).is_integer()) or 1900 <= abs(v) <= 2100:
            continue
        scales = (1, 100, 0.01, 1e3, 1e-3, 1e6, 1e-6)  # %, k, M style rewrites
        if not any(abs(v - k * s) <= max(0.51 * (1 if s == 1 else s), 0.011 * abs(v)) for k in known for s in scales):
            bad.append(tok)
    return bad


def make_insight_agent(svc: Services):
    def insight_agent(state: AgentState) -> dict:
        facts = state["facts"]
        payload = json.dumps({"facts": facts, "charts": [c["title"] for c in state.get("charts", [])]}, default=str)[:14000]
        try:
            out = svc.llm.structured(prompts.INSIGHT, f"Question: {state['message']}\n\nFACTS:\n{payload}", InsightOut,
                                     history=state.get("history"))
        except LLMError:
            n = facts.get("row_count", 0)
            return {"answer": f"The query returned {n} row(s). I couldn't generate a narrative explanation just now, "
                              "but the table and charts below are computed directly from your data.",
                    "insights": [], "follow_ups": [], "warnings": state.get("warnings", []) + ["LLM explanation unavailable."]}
        warnings = list(state.get("warnings", []))
        bad = unverified_numbers(" ".join([out.answer, *out.key_insights]), facts)
        if bad:
            warnings.append(f"Some figures in the explanation could not be verified against the computed data: {', '.join(bad[:5])}.")
        return {"answer": out.answer, "insights": out.key_insights[:4], "follow_ups": out.follow_ups[:3], "warnings": warnings}

    return insight_agent
