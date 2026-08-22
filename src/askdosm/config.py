"""Application configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ASKDOSM_", extra="ignore")

    chat_model: str = "qwen3:8b"
    embedding_model: str = "embeddinggemma"
    ollama_base_url: str = "http://localhost:11434"
    request_timeout: float = 30.0
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


def get_settings() -> Settings:
    return Settings()
