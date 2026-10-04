from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.services import Services
from app.db.metadata import scope_of


@dataclass
class ReportContext:
    title: str
    generated_at: str
    profile: dict[str, Any] | None
    dashboard_items: list[dict[str, Any]] = field(default_factory=list)
    insights: list[dict[str, Any]] = field(default_factory=list)  # {question, insight, sql}


def build_context(svc: Services, source_type: str, source_id: int) -> ReportContext:
    profile, name = None, f"{source_type} {source_id}"
    if source_type == "dataset":
        ds = svc.repo.get_dataset(source_id)
        if not ds:
            raise LookupError("Dataset not found")
        profile, name = ds.get("profile"), ds["name"]
    else:
        c = svc.repo.get_connection(source_id)
        if not c:
            raise LookupError("Connection not found")
        name = f"{c['name']} ({c['database']})"
    runs = svc.repo.recent_runs(source_type, source_id, 10)
    return ReportContext(
        title=f"Analysis report - {name}",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        profile=profile,
        dashboard_items=svc.repo.list_dashboard_items(scope_of(source_type, source_id)),
        insights=[{"question": r["question"], "insight": r["insight"], "sql": r["sql"]} for r in runs if r.get("insight")],
    )
