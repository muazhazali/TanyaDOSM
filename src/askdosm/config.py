"""Application configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ASKDOSM_", extra="ignore")

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    chat_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-small"
    request_timeout: float = 30.0
    cache_dir: Path = Path(".askdosm-cache")
    cache_ttl_hours: int = 24
    max_retries: int = 2
    catalogue_path: Path = Path("data/catalogue.json")


def get_settings() -> Settings:
    return Settings()

