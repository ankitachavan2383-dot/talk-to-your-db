from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel


def sanitize(obj: Any) -> Any:
    """Recursively convert numpy/pandas/pydantic objects into strict-JSON-safe Python."""
    if obj is None or obj is pd.NaT:
        return None
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (pd.Period, pd.Timedelta)):
        return str(obj)
    if isinstance(obj, BaseModel):
        return sanitize(obj.model_dump())
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return df_to_records(obj)
    if isinstance(obj, (pd.Series, np.ndarray)):
        return [sanitize(v) for v in obj.tolist()]
    return str(obj)


def df_to_records(df: pd.DataFrame, limit: int = 500) -> list[dict[str, Any]]:
    return sanitize(df.head(limit).to_dict(orient="records"))
