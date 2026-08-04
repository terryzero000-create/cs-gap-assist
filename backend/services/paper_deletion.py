from pathlib import Path

from backend.core.config import Settings
from backend.core.errors import ApiError
from backend.models.schemas import PaperDeleteResponse
from backend.rag.vector_store import clear_vector_store_cache, get_vector_store
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.vector_index import LEGACY_COLLECTION, VectorIndexManager


def delete_paper_data(
    settings: Settings,
    store: SQLiteStore,
    doc_id: str,
) -> PaperDeleteResponse:
    """Delete one paper from vectors, SQLite, and managed document storage."""
    try:
        manifest = store.paper_deletion_manifest(doc_id)
    except ValueError as exc:
        raise _paper_busy_error(exc) from exc
    if manifest is None:
        raise ApiError(
            "Paper not found.",
            404,
            error_code="PAPER_NOT_FOUND",
        )

    chunk_ids = list(manifest["chunk_ids"])
    if chunk_ids:
        try:
            manager = VectorIndexManager(settings)
            collection_names = {
                LEGACY_COLLECTION,
                manager.collection_name(),
                *manifest["vector_collections"],
            }
            for collection_name in collection_names:
                get_vector_store(
                    settings,
                    collection_name=str(collection_name),
                    create_if_missing=False,
                ).delete_chunks(chunk_ids)
            clear_vector_store_cache()
        except Exception as exc:
            raise ApiError(
                "Unable to remove the paper from the vector index.",
                503,
                error_code="PAPER_VECTOR_DELETE_FAILED",
                retryable=True,
            ) from exc

    try:
        deleted = store.delete_paper_records(doc_id)
    except KeyError as exc:
        raise ApiError(
            "Paper not found.",
            404,
            error_code="PAPER_NOT_FOUND",
        ) from exc
    except ValueError as exc:
        raise _paper_busy_error(exc) from exc

    deleted_files, warnings = _delete_managed_source_files(
        settings.documents_path,
        list(manifest["source_paths"]),
    )
    return PaperDeleteResponse(
        doc_id=doc_id,
        deleted_file_count=deleted_files,
        warnings=warnings,
        **deleted,
    )


def _delete_managed_source_files(
    documents_path: Path,
    source_paths: list[str],
) -> tuple[int, list[str]]:
    """Delete only files proven to live below the configured document root."""
    root = documents_path.resolve()
    deleted = 0
    warnings: list[str] = []
    for source_path in dict.fromkeys(source_paths):
        candidate = Path(source_path).resolve()
        if not candidate.is_relative_to(root):
            warnings.append(
                f"Skipped a source file outside the managed document directory: {candidate.name}"
            )
            continue
        try:
            if candidate.is_file():
                candidate.unlink()
                deleted += 1
            parent = candidate.parent
            if parent != root and parent.is_relative_to(root):
                try:
                    parent.rmdir()
                except OSError:
                    pass
        except OSError:
            warnings.append(f"Could not remove stored source file: {candidate.name}")
    return deleted, warnings


def _paper_busy_error(exc: ValueError) -> ApiError:
    if str(exc) == "PAPER_INGESTION_IN_PROGRESS":
        return ApiError(
            "Paper ingestion is still in progress.",
            409,
            error_code="PAPER_INGESTION_IN_PROGRESS",
            retryable=True,
        )
    return ApiError(
        "Paper cannot be deleted.",
        409,
        error_code="PAPER_DELETE_CONFLICT",
    )
