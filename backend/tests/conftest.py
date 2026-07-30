from collections.abc import Iterator

import pytest

from backend.core.config import get_settings
from backend.rag.vector_store import clear_vector_store_cache
from backend.services.vector_index import clear_vector_index_manager_cache


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch) -> Iterator[None]:
    """Keep every test offline and isolated from local application data."""
    monkeypatch.setenv("SQLITE_URL", str(tmp_path / "app.db"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("DEFAULT_CHAT_PROVIDER", "mock")
    monkeypatch.setenv("DEFAULT_CHAT_MODEL", "mock-chat")
    monkeypatch.setenv("DEFAULT_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("DEFAULT_EMBEDDING_MODEL", "mock-embedding")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("EXTERNAL_NETWORK_ENABLED", "false")
    get_settings.cache_clear()
    clear_vector_store_cache()
    clear_vector_index_manager_cache()
    yield
    get_settings.cache_clear()
    clear_vector_store_cache()
    clear_vector_index_manager_cache()
