from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api import citation, config, experiment, gap, knowledge, metrics, paper, paper_upload, reading, reproduction_agent, research_plan_agent, vector_index
from backend.core.config import get_settings
from backend.core.errors import register_error_handlers
from backend.core.security import ApiKeyMiddleware
from backend.rag.embedder import close_embedding_http_clients
from backend.repositories.sqlite_store import get_sqlite_store
from backend.services.pdf_parser import ocr_capability
from backend.services.paper_ingestion import get_ingestion_worker
from backend.services.vector_index import get_vector_index_manager

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run the durable local ingestion worker for the application lifetime."""
    runtime_settings = get_settings()
    get_sqlite_store(runtime_settings.sqlite_path)
    worker = get_ingestion_worker(runtime_settings)
    await worker.ensure_started()
    try:
        yield
    finally:
        await worker.stop()
        await close_embedding_http_clients()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiKeyMiddleware)
register_error_handlers(app)
app.include_router(config.router, prefix=settings.api_prefix)
app.include_router(citation.router, prefix=settings.api_prefix)
app.include_router(experiment.router, prefix=settings.api_prefix)
app.include_router(gap.router, prefix=settings.api_prefix)
app.include_router(knowledge.router, prefix=settings.api_prefix)
app.include_router(metrics.router, prefix=settings.api_prefix)
app.include_router(paper.router, prefix=settings.api_prefix)
app.include_router(paper_upload.router, prefix=settings.api_prefix)
app.include_router(reading.router, prefix=settings.api_prefix)
app.include_router(reproduction_agent.router, prefix=settings.api_prefix)
app.include_router(research_plan_agent.router, prefix=settings.api_prefix)
app.include_router(vector_index.router, prefix=settings.api_prefix)


@app.get(f"{settings.api_prefix}/health")
async def health_check() -> dict[str, str]:
    """Backward-compatible liveness alias."""
    return {"status": "ok"}


@app.get("/health/live")
@app.get(f"{settings.api_prefix}/health/live")
async def liveness_check() -> dict[str, str]:
    """Return process liveness without exposing dependency details."""
    return {"status": "ok"}


@app.get("/health/ready")
@app.get(f"{settings.api_prefix}/health/ready")
async def readiness_check() -> JSONResponse:
    """Report whether local storage and the active retrieval index are usable."""
    components: dict[str, dict[str, object]] = {}
    ready = True
    try:
        store = get_sqlite_store(get_settings().sqlite_path)
        store.ping()
        components["sqlite"] = {"status": "ready"}
        reupload_required = store.count_reupload_required()
        migration_ready = reupload_required == 0
        ready = ready and migration_ready
        components["data_migration"] = {
            "status": "ready" if migration_ready else "waiting_for_reupload",
            "reupload_required_count": reupload_required,
        }
    except Exception as exc:
        ready = False
        components["sqlite"] = {"status": "failed", "error": str(exc)}
    try:
        documents_path = get_settings().documents_path
        documents_path.mkdir(parents=True, exist_ok=True)
        components["documents"] = {"status": "ready", "path": str(documents_path)}
    except Exception as exc:
        ready = False
        components["documents"] = {"status": "failed", "error": str(exc)}
    try:
        index_status = get_vector_index_manager().status()
        index_ready = index_status["state"] in {"ready", "empty"}
        ready = ready and index_ready
        components["vector_index"] = {
            "status": "ready" if index_ready else "degraded",
            "state": index_status["state"],
            "missing_chunk_count": index_status["missing_chunk_count"],
            "orphan_vector_count": index_status["orphan_vector_count"],
        }
    except Exception as exc:
        ready = False
        components["vector_index"] = {"status": "failed", "error": str(exc)}
    if get_settings().default_embedding_provider == "xfyun-spark":
        embedding_ready = bool(
            get_settings().xfyun_spark_app_id
            and get_settings().xfyun_spark_api_key
            and get_settings().xfyun_spark_api_secret
        )
    else:
        embedding_ready = True
    ready = ready and embedding_ready
    components["embedding_config"] = {"status": "ready" if embedding_ready else "failed"}
    ocr_mode = get_settings().ocr_mode
    if ocr_mode == "disabled":
        components["ocr"] = {
            "status": "disabled",
            "mode": ocr_mode,
            "detail": "OCR is disabled by configuration",
        }
    else:
        ocr = ocr_capability()
        ocr_required = ocr_mode == "required"
        ocr_ready = ocr.available or not ocr_required
        ready = ready and ocr_ready
        components["ocr"] = {
            "status": "ready" if ocr.available else (
                "failed" if ocr_required else "unavailable"
            ),
            "mode": ocr_mode,
            "detail": ocr.detail,
        }
    auth_ready = (
        get_settings().app_env == "test"
        or bool(get_settings().app_api_key)
    )
    ready = ready and auth_ready
    components["api_auth"] = {
        "status": "ready" if auth_ready else "failed",
    }
    worker_ready = get_ingestion_worker(get_settings()).is_running
    ready = ready and worker_ready
    components["ingestion_worker"] = {"status": "ready" if worker_ready else "failed"}
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "components": components},
    )
