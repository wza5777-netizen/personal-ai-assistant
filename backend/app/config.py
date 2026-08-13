"""Application configuration loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database — real value comes from .env (DATABASE_URL)
    database_url: str = ""

    # LLM — real values come from .env (OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL)
    openai_api_key: str = ""
    openai_model: str = ""
    openai_base_url: str = ""

    # Embeddings (Volcano Ark) — real values come from .env
    # (EMBEDDING_BASE_URL / EMBEDDING_MODEL). Falls back to a deterministic hash
    # embedding when credentials are unavailable so the pipeline stays verifiable.
    embedding_base_url: str = ""
    embedding_model: str = ""

    # App environment: development | production
    app_env: str = "development"
    log_level: str = "INFO"

    # JWT secret used for admin auth (real value from .env). Never logged.
    jwt_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
