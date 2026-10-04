from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.services import Services
from app.db.metadata import MetadataRepo


class FakeLLM:
    """Scripted LLM: handlers keyed by response schema class."""

    def __init__(self, handlers: dict, chat_reply: str = "hello") -> None:
        self.handlers, self.chat_reply, self.calls = handlers, chat_reply, []

    def structured(self, system, user, schema, history=None):
        self.calls.append((schema.__name__, user))
        h = self.handlers[schema]
        return h(user) if callable(h) else h

    def chat(self, system, user, history=None):
        return self.chat_reply


@pytest.fixture
def sales_df() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-01", "2024-12-31", freq="D")
    rows = []
    for d in dates:
        for region in ("North", "South"):
            for product in ("Laptop", "Chair"):
                base = 100 if product == "Laptop" else 40
                if d.month == 12 and product == "Laptop" and region == "North":
                    base = 20  # engineered drop
                rows.append({"order_id": len(rows) + 1, "order_date": d.strftime("%Y-%m-%d"), "region": region,
                             "product": product, "revenue": float(base + rng.normal(0, 3)), "quantity": int(rng.integers(1, 5))})
    df = pd.DataFrame(rows)
    df.loc[5, "revenue"] = 5000.0  # outlier
    df.loc[10:12, "region"] = None
    return pd.concat([df, df.iloc[[0]]], ignore_index=True)  # one duplicate


@pytest.fixture
def make_services(tmp_path):
    def _make(llm) -> Services:
        settings = Settings(data_dir=tmp_path / "data", app_secret_key=Fernet.generate_key().decode(),
                            metadata_db_url=f"sqlite:///{tmp_path / 'meta.db'}", xai_api_key="test")
        return Services(settings=settings, llm=llm, repo=MetadataRepo(settings.metadata_db_url, settings.app_secret_key))
    return _make
