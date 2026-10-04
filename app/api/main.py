from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.agents.graph import build_graph
from app.api.deps import require_token
from app.api.routers import chat, connections, dashboard, datasets, reports
from app.core.services import Services


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.svc = Services()
    app.state.graph = build_graph(app.state.svc)
    yield


app = FastAPI(title="Agentic Data Analyst & BI Assistant", version="1.0.0", lifespan=lifespan)
for r in (datasets.router, connections.router, chat.router, dashboard.router, reports.router):
    app.include_router(r, dependencies=[Depends(require_token)])


@app.get("/health")
def health():
    return {"status": "ok"}
