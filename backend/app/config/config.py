from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

# Resolve .env path relative to the project root (stock-research/)
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://postgres:123123@localhost:5432/stockapp"

    # API Keys
    fmp_api_key: str = ""
    finnhub_api_key: str = ""
    anthropic_api_key: str = ""
    fred_api_key: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
