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
    cache_ttl_hours: int = 24
    max_retries: int = 2
    catalogue_path: Path = Path("data/catalogue.json")


def get_settings() -> Settings:
    return Settings()
