from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = os.getenv("GROQ_API_KEY")
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.1
    llm_timeout_s: int = 90

    metadata_db_url: str = "postgresql+psycopg://app:app@localhost:5432/appmeta"
    app_secret_key: str = os.getenv("APP_SECRET_KEY")
    api_token: str = os.getenv("API_TOKEN")

    data_dir: Path = Path("./data")
    max_upload_mb: int = 100

    sql_timeout_s: int = 15
    sql_default_limit: int = 1000
    sql_max_rows: int = 10_000
    sql_max_retries: int = 2
    require_readonly_role: bool = True
    send_sample_values_to_llm: bool = False

    api_base_url: str = "http://localhost:8000"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"


@lru_cache
def get_settings() -> Settings:
    return Settings()
