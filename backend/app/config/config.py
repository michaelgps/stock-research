import json
from pathlib import Path
from typing import Annotated

from pydantic_settings import BaseSettings, NoDecode
from pydantic import field_validator
from functools import lru_cache

# Resolve .env path relative to the project root (stock-research/)
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:123123@localhost:5432/stockapp"

    # API Keys
    fmp_api_key: str = ""
    finnhub_api_key: str = ""
    alpha_vantage_api_key: str = ""
    anthropic_api_key: str = ""
    fred_api_key: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # CORS
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                return json.loads(raw)
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
