from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "CS Gap Assist"
    api_prefix: str = "/api/v1"
    sqlite_url: str = "data/app.db"
    chroma_dir: str = "data/chroma"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    default_chat_provider: str = "deepseek"
    default_chat_model: str = "deepseek-v4-pro"
    openai_api_key: str | None = None
    default_embedding_provider: str = "openai"
    default_embedding_model: str = "text-embedding-3-small"
    enable_semantic_scholar: bool = False
    external_search_timeout_seconds: float = 3.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def sqlite_path(self) -> Path:
        """Return the filesystem path for the SQLite database."""
        return Path(self.sqlite_url.replace("sqlite:///", ""))


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
