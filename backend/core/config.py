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
    openai_base_url: str = "https://api.openai.com/v1"
    default_embedding_provider: str = "xfyun-spark"
    default_embedding_model: str = "query"
    local_bge_m3_base_url: str = "http://127.0.0.1:11434"
    local_bge_m3_model: str = "bge-m3"
    xfyun_spark_app_id: str | None = None
    xfyun_spark_api_key: str | None = None
    xfyun_spark_api_secret: str | None = None
    xfyun_spark_embedding_url: str = "https://emb-cn-huabei-1.xf-yun.com"
    xfyun_spark_embedding_path: str = "/"
    enable_openalex: bool = False
    openalex_api_key: str | None = None
    openalex_base_url: str = "https://api.openalex.org/works"
    arxiv_base_url: str = "https://export.arxiv.org/api/query"
    arxiv_user_agent: str = "CS-Gap-Assist/0.1 (literature-research-client)"
    arxiv_min_interval_seconds: float = 3.0
    arxiv_cache_ttl_seconds: float = 300.0
    external_search_timeout_seconds: float = 3.0
    external_network_enabled: bool = True
    rag_min_semantic_score: float = 0.35
    rag_min_lexical_score: float = 0.05
    rag_max_context_tokens: int = 6000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def sqlite_path(self) -> Path:
        """Return the filesystem path for the SQLite database."""
        return Path(self.sqlite_url.replace("sqlite:///", ""))


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
