from collections.abc import Iterator
import os

import pytest

_LIVE_SMOKE = os.environ.get("RUN_LIVE_SMOKE", "").lower() == "true"
if not _LIVE_SMOKE:
    # This runs before test modules import backend.main, so route and CORS
    # construction cannot inherit a developer's local .env configuration.
    os.environ.update(
        {
            "APP_ENV": "test",
            "APP_API_KEY": "",
            "ALLOW_SYNTHETIC_MODE": "true",
            "DEFAULT_CHAT_PROVIDER": "mock",
            "DEFAULT_CHAT_MODEL": "mock-chat",
            "DEFAULT_EMBEDDING_PROVIDER": "mock",
            "DEFAULT_EMBEDDING_MODEL": "mock-embedding",
            "DEEPSEEK_API_KEY": "",
            "OPENAI_API_KEY": "",
            "EXTERNAL_NETWORK_ENABLED": "false",
            "ENABLE_OPENALEX": "false",
            "OPENALEX_API_KEY": "",
            "XFYUN_SPARK_APP_ID": "",
            "XFYUN_SPARK_API_KEY": "",
            "XFYUN_SPARK_API_SECRET": "",
            "OCR_MODE": "auto",
        }
    )

from backend.core.config import get_settings
from backend.rag.vector_store import clear_vector_store_cache
from backend.repositories.sqlite_store import get_sqlite_store
from backend.services.pdf_parser import ocr_capability
from backend.services.vector_index import clear_vector_index_manager_cache


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch) -> Iterator[None]:
    """Keep every test offline and isolated from local application data."""
    if _LIVE_SMOKE:
        yield
        return

    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "app.db"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("DOCUMENT_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("ALLOW_SYNTHETIC_MODE", "true")
    monkeypatch.setenv("DEFAULT_CHAT_PROVIDER", "mock")
    monkeypatch.setenv("DEFAULT_CHAT_MODEL", "mock-chat")
    monkeypatch.setenv("DEFAULT_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("DEFAULT_EMBEDDING_MODEL", "mock-embedding")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("EXTERNAL_NETWORK_ENABLED", "false")
    monkeypatch.setenv("ENABLE_OPENALEX", "false")
    monkeypatch.setenv("OPENALEX_API_KEY", "")
    monkeypatch.setenv("XFYUN_SPARK_APP_ID", "")
    monkeypatch.setenv("XFYUN_SPARK_API_KEY", "")
    monkeypatch.setenv("XFYUN_SPARK_API_SECRET", "")
    monkeypatch.setenv("OCR_MODE", "auto")
    get_settings.cache_clear()
    get_sqlite_store.cache_clear()
    ocr_capability.cache_clear()
    clear_vector_store_cache()
    clear_vector_index_manager_cache()
    yield
    get_settings.cache_clear()
    get_sqlite_store.cache_clear()
    ocr_capability.cache_clear()
    clear_vector_store_cache()
    clear_vector_index_manager_cache()
