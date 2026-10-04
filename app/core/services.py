"""Composition root: wires settings, LLM, metadata repo, dataset cache, DB engines and schema cache."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine

from app.core.config import Settings, get_settings
from app.data.loader import load_dataframe
from app.db.connectors import DialectAdapter, get_adapter, test_connection
from app.db.metadata import MetadataRepo
from app.db.schema_inspector import SchemaInfo, inspect_schema
from app.llm.client import LLM, GroqClient

SCHEMA_TTL_S = 300


class Services:
    def __init__(self, settings: Settings | None = None, llm: LLM | None = None, repo: MetadataRepo | None = None) -> None:
        self.settings = settings or get_settings()
        self.llm: LLM = llm or GroqClient(self.settings)
        self.repo = repo or MetadataRepo(self.settings.metadata_db_url, self.settings.app_secret_key)
        self.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.settings.results_dir.mkdir(parents=True, exist_ok=True)
        self._engines: dict[int, tuple[Engine, DialectAdapter]] = {}
        self._schemas: dict[int, tuple[float, SchemaInfo]] = {}
        self._frames: dict[tuple[str, float], pd.DataFrame] = {}

    # --- files ---
    def dataset_frame(self, dataset_id: int) -> pd.DataFrame:
        ds = self.repo.get_dataset(dataset_id)
        if not ds:
            raise LookupError(f"Dataset {dataset_id} not found")
        path = Path(ds["stored_path"])
        key = (str(path), path.stat().st_mtime)
        if key not in self._frames:
            if len(self._frames) >= 4:
                self._frames.pop(next(iter(self._frames)))
            self._frames[key] = load_dataframe(path)
        return self._frames[key]  # callers must treat as read-only

    # --- databases ---
    def engine_for(self, conn_id: int) -> tuple[Engine, DialectAdapter]:
        if conn_id not in self._engines:
            c = self.repo.get_connection(conn_id, with_secret=True)
            if not c:
                raise LookupError(f"Connection {conn_id} not found")
            adapter = get_adapter(c["dialect"])
            url = adapter.build_url(c["host"], c["port"], c["database"], c["username"], c["password"])
            engine = adapter.make_engine(url, self.settings.sql_timeout_s)
            test_connection(engine, adapter, self.settings.require_readonly_role)
            self._engines[conn_id] = (engine, adapter)
        return self._engines[conn_id]

    def schema_for(self, conn_id: int, refresh: bool = False) -> SchemaInfo:
        cached = self._schemas.get(conn_id)
        if cached and not refresh and time.time() - cached[0] < SCHEMA_TTL_S:
            return cached[1]
        engine, adapter = self.engine_for(conn_id)
        info = inspect_schema(engine, adapter)
        self._schemas[conn_id] = (time.time(), info)
        return info

    def forget_connection(self, conn_id: int) -> None:
        pair = self._engines.pop(conn_id, None)
        if pair:
            pair[0].dispose()
        self._schemas.pop(conn_id, None)
