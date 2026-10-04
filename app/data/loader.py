from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pandas as pd

ALLOWED_EXT = {".csv": "csv", ".tsv": "csv", ".xlsx": "excel", ".xls": "excel", ".json": "json", ".parquet": "parquet"}


class LoadError(ValueError):
    pass


def save_original(content: bytes, filename: str, uploads_dir: Path, max_mb: int) -> tuple[Path, str]:
    """Persist the upload exactly as received and mark it read-only. Analysis never writes to it."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise LoadError(f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXT)}")
    if len(content) > max_mb * 1024 * 1024:
        raise LoadError(f"File exceeds {max_mb} MB limit.")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)[:120] or f"upload{ext}"
    target_dir = uploads_dir / uuid.uuid4().hex
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / safe
    path.write_bytes(content)
    os.chmod(path, 0o444)
    return path, ALLOWED_EXT[ext]


def load_dataframe(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext in (".csv", ".tsv"):
            df = _read_csv(path)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(path)
        elif ext == ".json":
            df = _read_json(path)
        elif ext == ".parquet":
            df = pd.read_parquet(path)
        else:
            raise LoadError(f"Unsupported file type '{ext}'")
    except LoadError:
        raise
    except Exception as exc:
        raise LoadError(f"Could not read file: {exc.__class__.__name__}: {str(exc)[:200]}") from exc
    if df.empty and len(df.columns) == 0:
        raise LoadError("File contains no data.")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _read_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, sep=None, engine="python", encoding=enc)
        except UnicodeDecodeError:
            continue
    raise LoadError("Could not decode CSV (tried utf-8 and latin-1).")


def _read_json(path: Path) -> pd.DataFrame:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return pd.read_json(path, lines=True)  # JSON Lines
    if isinstance(raw, dict):
        lists = [v for v in raw.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        raw = lists[0] if lists else [raw]
    return pd.json_normalize(raw)
