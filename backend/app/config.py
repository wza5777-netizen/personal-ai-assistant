"""Application configuration loaded from environment variables.

Environment files (see .gitignore — .env and .env.dev are NOT committed):
  - .env.dev : local development config (committed as a safe template, no secrets)
  - .env     : production/fallback config; on Render, real secrets are injected
               via the dashboard (see render.yaml) and override any file values

Both files are loaded in order (.env.dev first, then .env). On a developer
machine .env.dev exists and wins; on production .env.dev is absent so .env
(or the dashboard-injected environment variables) is used. Real environment
variables always take precedence over any dotenv file.
"""
from functools import lru_cache
from os import environ
from pathlib import Path
import json

from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

_BASE_DIR = Path(__file__).resolve().parent.parent


def _env_file_for(app_env: str) -> Path:
    """Pick the dotenv file based on the active environment."""
    if app_env.lower() == "development":
        dev_file = _BASE_DIR / ".env.dev"
        if dev_file.exists():
            return dev_file
    return _BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # App environment: development | production
    app_env: str = "development"

    # Database — real value comes from the env file / environment (DATABASE_URL)
    database_url: str = ""

    # LLM — real values come from the env file / environment
    # (OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL)
    openai_api_key: str = ""
    openai_model: str = ""
    openai_base_url: str = ""

    # Embeddings (Volcano Ark) — real values come from the env file / environment
    # (EMBEDDING_BASE_URL / EMBEDDING_MODEL). Falls back to a deterministic hash
    # embedding when credentials are unavailable so the pipeline stays verifiable.
    embedding_base_url: str = ""
    embedding_model: str = ""

    log_level: str = "INFO"

    # JWT secret used for admin + user auth (real value from env). Never logged.
    jwt_secret: str = ""

    # User access-token lifetime (minutes). Used by create_user_access_token.
    access_token_expire_minutes: int = 60 * 24  # 1 day default

    # CORS: comma-separated extra allowed origins for production
    # (e.g. "https://app.onrender.com,https://api.onrender.com").
    cors_origins: str = ""

    # Model-aware pricing. JSON mapping of model name -> per-1M-token prices (USD).
    # Example:
    #   MODEL_PRICING={"gpt-4o-mini":{"input_per_1m":0.15,"output_per_1m":0.60},
    #                  "deepseek-chat":{"input_per_1m":0.27,"output_per_1m":1.10}}
    # If a model is absent, its cost is reported as null (unavailable) rather than
    # being guessed from another model.
    model_pricing: str = ""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Read APP_ENV from the process environment first so we can choose the
        # correct dotenv file. Priority: env vars > chosen .env file > defaults.
        app_env = environ.get("APP_ENV") or "development"
        dotenv_path = _env_file_for(app_env)
        chosen = DotEnvSettingsSource(
            settings_cls,
            env_file=str(dotenv_path),
            case_sensitive=False,
        )
        # env_settings is included so real environment variables always win
        # over the chosen dotenv file. (kept intentionally)
        _ = env_settings
        return (
            init_settings,
            env_settings,
            chosen,
            file_secret_settings,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def parse_model_pricing(raw: str) -> dict[str, dict[str, float]]:
    """Parse the ``MODEL_PRICING`` JSON env var into a pricing map.

    Returns a dict: {model_name: {"input_per_1m": float, "output_per_1m": float}}.
    Invalid/empty input yields an empty dict (unknown models -> null cost).
    """
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, float]] = {}
    for name, prices in data.items():
        if not isinstance(prices, dict):
            continue
        in_price = prices.get("input_per_1m")
        out_price = prices.get("output_per_1m")
        if in_price is None or out_price is None:
            continue
        try:
            result[str(name)] = {
                "input_per_1m": float(in_price),
                "output_per_1m": float(out_price),
            }
        except (TypeError, ValueError):
            continue
    return result
