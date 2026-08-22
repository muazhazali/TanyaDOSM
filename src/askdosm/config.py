"""Application configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ASKDOSM_", extra="ignore")

    chat_model: str = "openai/gpt-oss-20b"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    embedding_model: str = "@cf/baai/bge-m3"
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_base_url: str = "https://api.cloudflare.com/client/v4/accounts"
    request_timeout: float = 30.0
    provider_max_retries: int = 2
    cache_dir: Path = Path(".askdosm-cache")
    cache_ttl_hours: int = 720
    monitor_interval_hours: int = 168
    max_retries: int = 2
    catalogue_path: Path = Path("data/catalogue.json")
    run_db_path: Path = Path(".askdosm-cache/runs.sqlite3")
    run_retention_days: int = 7
    max_concurrent_runs: int = 1
    max_question_length: int = 500
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def require_groq_credentials(self) -> None:
        if not self.groq_api_key.strip():
            raise RuntimeError("ASKDOSM_GROQ_API_KEY is required")


def get_settings() -> Settings:
    return Settings()
