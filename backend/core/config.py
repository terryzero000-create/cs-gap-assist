import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    app_name: str = "CS Gap Assist"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    app_api_key: str | None = None
    allow_synthetic_mode: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    sqlite_url: str = "data/app.db"
    chroma_dir: str = "data/chroma"
    document_dir: str = "data/documents"
    max_pdf_bytes: int = 50 * 1024 * 1024
    max_pdf_pages: int = 500
    legacy_sync_max_pdf_bytes: int = 10 * 1024 * 1024
    legacy_sync_max_pdf_pages: int = 100
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    default_chat_provider: Literal["deepseek", "openai", "mock"] = "deepseek"
    default_chat_model: str = "deepseek-v4-pro"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    default_embedding_provider: Literal["xfyun-spark", "local-bge-m3", "mock"] = "xfyun-spark"
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
    rag_max_prompt_bytes: int = Field(default=100_000, ge=4096)
    rag_final_top_k: int = Field(default=8, ge=1, le=20)
    rag_vector_weight: float = Field(default=0.55, ge=0.0, le=1.0)
    rag_lexical_weight: float = Field(default=0.45, ge=0.0, le=1.0)
    rag_rrf_k: int = Field(default=60, ge=1)
    rag_mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    enable_reranker: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    xfyun_max_text_bytes: int = Field(default=6000, ge=512)
    xfyun_embedding_concurrency: int = Field(default=4, ge=1, le=16)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def __init__(self, **values: Any) -> None:
        """Never allow a developer .env file to influence test settings."""
        requested_env = values.get("app_env") or os.environ.get("APP_ENV")
        if requested_env == "test":
            values["_env_file"] = None
        super().__init__(**values)

    @model_validator(mode="after")
    def validate_runtime_profile(self) -> "Settings":
        """Reject incompatible or unsafe deployment profiles at startup."""
        if not 0.999 <= self.rag_vector_weight + self.rag_lexical_weight <= 1.001:
            raise ValueError("RAG vector and lexical weights must sum to 1.")
        if self.app_env == "production" and self.allow_synthetic_mode:
            raise ValueError("Synthetic mode cannot be enabled in production.")
        if self.app_env == "production" and "*" in self.allowed_cors_origins:
            raise ValueError("Wildcard CORS is not allowed in production.")
        return self

    @property
    def sqlite_path(self) -> Path:
        """Return the filesystem path for the SQLite database."""
        return Path(self.sqlite_url.replace("sqlite:///", ""))

    @property
    def documents_path(self) -> Path:
        """Return the filesystem path for persisted source PDFs."""
        return Path(self.document_dir)

    @property
    def allowed_cors_origins(self) -> list[str]:
        """Return the configured exact browser origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def synthetic_mode_enabled(self) -> bool:
        """Return whether explicitly synthetic providers may be selected."""
        return self.app_env == "test" or self.allow_synthetic_mode


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
