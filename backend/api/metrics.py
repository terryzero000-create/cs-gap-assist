from fastapi import APIRouter

from backend.core.config import get_settings
from backend.repositories.sqlite_store import get_sqlite_store


router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("")
async def operational_metrics() -> dict[str, object]:
    """Return aggregate local performance statistics only."""
    settings = get_settings()
    return {
        "metrics": get_sqlite_store(settings.sqlite_path).metric_summary(),
        "privacy": {
            "contains_api_keys": False,
            "contains_paper_text": False,
        },
    }
