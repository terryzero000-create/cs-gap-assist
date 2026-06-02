from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import config, experiment, gap, paper, reading
from backend.core.config import get_settings
from backend.core.errors import register_error_handlers

settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(config.router, prefix=settings.api_prefix)
app.include_router(experiment.router, prefix=settings.api_prefix)
app.include_router(gap.router, prefix=settings.api_prefix)
app.include_router(paper.router, prefix=settings.api_prefix)
app.include_router(reading.router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health")
async def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}
