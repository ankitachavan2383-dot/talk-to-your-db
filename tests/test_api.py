"""API smoke test: upload -> profile -> dashboard -> reports (SQLite metadata, no LLM calls)."""
import io

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("METADATA_DB_URL", f"sqlite:///{tmp_path / 'm.db'}")
    monkeypatch.setenv("APP_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("API_TOKEN", "tok")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.api.main import app
    with TestClient(app) as c:
        c.headers["Authorization"] = "Bearer tok"
        yield c
    get_settings.cache_clear()


def test_auth_required(client):
    assert client.get("/datasets", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/health").status_code == 200


def test_upload_profile_dashboard_reports(client, sales_df):
    buf = io.BytesIO(sales_df.to_csv(index=False).encode())
    r = client.post("/datasets", files={"file": ("sales.csv", buf)})
    assert r.status_code == 200, r.text
    ds = r.json()
    assert ds["rows"] == len(sales_df) and ds["profile"]["kpis"]

    assert client.post("/datasets", files={"file": ("x.exe", io.BytesIO(b"x"))}).status_code == 400

    svc = client.app.state.svc
    svc.repo.add_dashboard_item(f"dataset:{ds['id']}", "table", "Top", {"rows": [{"a": "=cmd()", "b": 1}]})
    assert len(client.get("/dashboard", params={"source_type": "dataset", "source_id": ds["id"]}).json()) == 1

    for fmt, magic in (("html", b"<!doctype html>"), ("pdf", b"%PDF"), ("xlsx", b"PK")):
        rep = client.get(f"/reports/{fmt}", params={"source_type": "dataset", "source_id": ds["id"]})
        assert rep.status_code == 200 and rep.content.startswith(magic), fmt
