import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from backend.core.config import Settings
from backend.core.errors import ApiError
from backend.core.sanitize import safe_exception_message
from backend.models.schemas import PaperChunk, PaperUploadTaskResponse
from backend.repositories.sqlite_store import get_sqlite_store
from backend.services.chunker import CHUNKER_VERSION
from backend.services.pdf_parser import PdfParser, PdfValidationError
from backend.services.vector_index import VectorIndexManager, configured_embedding_provider


class IngestionFailure(RuntimeError):
    """Internal failure with an API-safe code and retry policy."""

    def __init__(self, message: str, error_code: str, retryable: bool) -> None:
        self.error_code = error_code
        self.retryable = retryable
        super().__init__(message)


class PaperIngestionService:
    """Process one durable paper revision through parsing and indexing."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = get_sqlite_store(settings.sqlite_path)

    async def process(self, upload_id: str) -> None:
        """Advance one upload to ready or a truthful failed state."""
        upload = self.store.get_upload(upload_id)
        if upload is None:
            return
        if upload["status"] == "ready":
            return
        total_started = time.perf_counter()
        try:
            stage_started = time.perf_counter()
            self.store.update_upload_status(
                upload_id,
                "validating",
                increment_attempt=True,
            )
            content = Path(str(upload["source_path"])).read_bytes()
            parser = PdfParser(
                max_pages=self.settings.max_pdf_pages,
                max_payload_bytes=self.settings.xfyun_max_text_bytes,
                ocr_mode=self.settings.ocr_mode,
            )
            validation = parser.validate(content)
            self._record_stage("validating", stage_started)
            stage_started = time.perf_counter()
            parsed = await asyncio.to_thread(
                parser.parse,
                content,
                str(upload["title"]),
                doc_id=str(upload["doc_id"]),
                revision_id=str(upload["revision_id"]),
            )
            self.store.update_upload_status(
                upload_id,
                "parsed",
                page_count=validation.page_count,
            )
            self._record_stage("parsed", stage_started)
            stage_started = time.perf_counter()
            chunks = [
                PaperChunk(
                    chunk_id=item.chunk_id,
                    doc_id=str(upload["doc_id"]),
                    revision_id=str(upload["revision_id"]),
                    page=item.page,
                    page_end=item.page_end,
                    ordinal=item.ordinal,
                    text=item.text,
                    section_path=item.section_path,
                    char_start=item.char_start,
                    char_end=item.char_end,
                    block_type=item.block_type,
                    chunker_version=item.chunker_version,
                    content_hash=item.content_hash,
                    injection_flagged=item.injection_flagged,
                )
                for item in parsed
            ]
            warning_codes: list[str] = list(parser.warning_codes)
            warnings: list[str] = list(parser.warnings)
            if any(chunk.injection_flagged for chunk in chunks):
                warning_codes.append("SOURCE_PROMPT_INJECTION_FLAGGED")
                warnings.append(
                    "Instruction-like text was isolated as untrusted evidence."
                )
            formula_pages = sorted(
                {
                    chunk.page
                    for chunk in chunks
                    if chunk.block_type == "formula"
                }
            )
            if formula_pages:
                warning_codes.append("FORMULA_VISUAL_VERIFICATION_REQUIRED")
                warnings.append(
                    "Formula regions on pages "
                    f"{', '.join(str(page) for page in formula_pages)} were "
                    "preserved with page locations but "
                    "must be verified against the source PDF; no missing "
                    "symbols were guessed."
                )
            self.store.store_revision_chunks(str(upload["revision_id"]), chunks)
            self.store.update_upload_status(
                upload_id,
                "chunked",
                warning_codes=warning_codes,
                warnings=warnings,
            )
            self._record_stage("chunked", stage_started)

            stage_started = time.perf_counter()
            self.store.update_upload_status(upload_id, "embedding")
            provider = configured_embedding_provider(self.settings, document=True)
            result = await provider.embed([chunk.text for chunk in chunks])
            self.store.record_metric("embedding.calls", 1, "count")
            self.store.record_metric(
                "embedding.payload_bytes",
                sum(len(chunk.text.encode("utf-8")) for chunk in chunks),
                "bytes",
            )
            manager = VectorIndexManager(self.settings)
            if result.is_fallback or not result.vectors:
                raise IngestionFailure(
                    "; ".join(result.warnings) or "Embedding provider returned no vectors.",
                    "EMBEDDING_UNAVAILABLE",
                    True,
                )
            if result.profile != manager.profile:
                raise IngestionFailure(
                    f"Embedding profile mismatch: expected {manager.profile.key}, got {result.profile.key}.",
                    "EMBEDDING_PROFILE_MISMATCH",
                    False,
                )
            self._record_stage("embedding", stage_started)
            stage_started = time.perf_counter()
            manager.add_chunks(chunks, result.vectors)
            self.store.update_upload_status(
                upload_id,
                "indexed",
                embedding_profile_key=manager.profile.key,
            )
            self._record_stage("indexed", stage_started)
            previous_revision = self.store.activate_upload(upload_id)
            if previous_revision and previous_revision != upload["revision_id"]:
                self._cleanup_revision_chunks(manager, previous_revision)
            self._cleanup_failed_revisions(
                manager,
                doc_id=str(upload["doc_id"]),
                active_revision_id=str(upload["revision_id"]),
            )
        except PdfValidationError as exc:
            self._fail(upload_id, str(exc), exc.error_code, exc.retryable)
        except IngestionFailure as exc:
            self._fail(upload_id, str(exc), exc.error_code, exc.retryable)
        except ApiError as exc:
            self._fail(
                upload_id,
                exc.message,
                exc.error_code if exc.error_code != "API_ERROR" else "INDEX_WRITE_FAILED",
                exc.retryable or exc.code >= 500,
            )
        except Exception as exc:
            self._fail(
                upload_id,
                safe_exception_message(exc),
                "INGESTION_FAILED",
                True,
            )
        finally:
            self.store.record_metric(
                "ingestion.total",
                (time.perf_counter() - total_started) * 1000,
                "ms",
            )

    def _record_stage(self, stage: str, started: float) -> None:
        self.store.record_metric(
            f"ingestion.stage.{stage}",
            (time.perf_counter() - started) * 1000,
            "ms",
        )

    def _fail(self, upload_id: str, message: str, error_code: str, retryable: bool) -> None:
        self.store.update_upload_status(
            upload_id,
            "failed",
            retryable=retryable,
            error_code=error_code,
            error_detail=message[:4000],
        )
        record = self.store.get_upload(upload_id)
        if record is None:
            return
        chunk_ids = self.store.revision_chunk_ids(str(record["revision_id"]))
        vectors_removed = True
        if chunk_ids:
            try:
                manager = VectorIndexManager(self.settings)
                manager.store(create_if_missing=False).delete_chunks(chunk_ids)
                self.store.delete_vector_entries(chunk_ids, manager.profile.key)
            except Exception:
                vectors_removed = False
                self._record_reconciliation_pending()
        if retryable or not vectors_removed:
            return
        try:
            if chunk_ids:
                self.store.delete_revision_chunks(str(record["revision_id"]))
            self._delete_managed_source_file(str(record["source_path"]))
        except Exception:
            self._record_reconciliation_pending()

    def _cleanup_revision_chunks(
        self,
        manager: VectorIndexManager,
        revision_id: str,
    ) -> bool:
        """Remove vectors and chunks only after a revision is no longer active."""
        chunk_ids = self.store.revision_chunk_ids(revision_id)
        try:
            if chunk_ids:
                manager.store(create_if_missing=False).delete_chunks(chunk_ids)
                self.store.delete_vector_entries(chunk_ids, manager.profile.key)
            self.store.delete_revision_chunks(revision_id)
            return True
        except Exception:
            self._record_reconciliation_pending()
            return False

    def _cleanup_failed_revisions(
        self,
        manager: VectorIndexManager,
        *,
        doc_id: str,
        active_revision_id: str,
    ) -> None:
        """Reclaim failed revisions once another revision is safely active."""
        manifests = self.store.failed_revision_cleanup_manifests(
            doc_id,
            exclude_revision_id=active_revision_id,
        )
        for manifest in manifests:
            revision_id = str(manifest["revision_id"])
            if self._cleanup_revision_chunks(manager, revision_id):
                self._delete_managed_source_file(str(manifest["source_path"]))

    def _delete_managed_source_file(self, source_path: str) -> None:
        """Delete an inactive source only when it is below the managed document root."""
        root = self.settings.documents_path.resolve()
        candidate = Path(source_path).resolve()
        if not candidate.is_relative_to(root):
            self._record_reconciliation_pending()
            return
        try:
            candidate.unlink(missing_ok=True)
            if candidate.parent != root:
                try:
                    candidate.parent.rmdir()
                except OSError:
                    pass
        except OSError:
            self._record_reconciliation_pending()

    def _record_reconciliation_pending(self) -> None:
        self.store.record_metric(
            "ingestion.reconciliation_pending",
            1,
            "count",
        )


@dataclass
class IngestionWorker:
    """One process-local worker backed by durable SQLite upload state."""

    settings: Settings
    _queue: asyncio.Queue[str] | None = None
    _runner: asyncio.Task[None] | None = None
    _loop_id: int | None = None
    _queued: set[str] = field(default_factory=set)

    @property
    def is_running(self) -> bool:
        """Return whether the local worker task is alive."""
        return bool(self._runner and not self._runner.done())

    async def ensure_started(self) -> None:
        """Start a worker on the current event loop and recover interrupted state."""
        loop = asyncio.get_running_loop()
        loop_id = id(loop)
        if self._runner and not self._runner.done() and self._loop_id == loop_id:
            return
        if self._runner and not self._runner.done():
            self._runner.cancel()
        self._queue = asyncio.Queue()
        self._loop_id = loop_id
        self._queued.clear()
        get_sqlite_store(self.settings.sqlite_path).recover_interrupted_uploads()
        try:
            VectorIndexManager(self.settings).reconcile_orphan_vectors()
        except Exception:
            # Readiness will report a degraded index; startup must still expose
            # the retry endpoint for interrupted uploads.
            pass
        self._runner = asyncio.create_task(self._run())

    async def enqueue(self, upload_id: str) -> None:
        """Queue an upload at most once in this process."""
        await self.ensure_started()
        assert self._queue is not None
        if upload_id in self._queued:
            return
        self._queued.add(upload_id)
        await self._queue.put(upload_id)

    async def stop(self) -> None:
        """Stop the process-local worker."""
        if self._runner and not self._runner.done():
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
        self._runner = None

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            upload_id = await self._queue.get()
            try:
                await PaperIngestionService(self.settings).process(upload_id)
            finally:
                self._queued.discard(upload_id)
                self._queue.task_done()


_WORKERS: dict[tuple[str, str], IngestionWorker] = {}


def get_ingestion_worker(settings: Settings) -> IngestionWorker:
    """Return the worker associated with one local data root."""
    key = (str(settings.sqlite_path.resolve()), str(settings.documents_path.resolve()))
    worker = _WORKERS.get(key)
    if worker is None:
        worker = IngestionWorker(settings)
        _WORKERS[key] = worker
    return worker


def upload_response(record: dict[str, object], api_prefix: str) -> PaperUploadTaskResponse:
    """Convert a durable upload row into its public response."""
    import json

    return PaperUploadTaskResponse(
        upload_id=str(record["upload_id"]),
        doc_id=str(record["doc_id"]),
        revision_id=str(record["revision_id"]),
        title=str(record["title"]),
        status=str(record["status"]),
        status_url=f"{api_prefix}/paper-uploads/{record['upload_id']}",
        retryable=bool(record.get("retryable")),
        error_code=str(record["error_code"]) if record.get("error_code") else None,
        error=str(record["error_detail"]) if record.get("error_detail") else None,
        page_count=int(record["page_count"]) if record.get("page_count") is not None else None,
        chunk_count=int(record.get("chunk_count") or 0),
        warning_codes=json.loads(str(record.get("warning_codes") or "[]")),
        warnings=json.loads(str(record.get("warnings") or "[]")),
    )


async def persist_upload_file(
    *,
    source: object,
    destination: Path,
    max_bytes: int,
) -> tuple[str, int]:
    """Stream an UploadFile-like object to disk while hashing and enforcing limits."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".uploading")
    digest = hashlib.sha256()
    size = 0
    try:
        with temporary.open("wb") as handle:
            while True:
                chunk = await source.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ApiError(
                        f"PDF exceeds the {max_bytes}-byte limit.",
                        413,
                        error_code="PDF_TOO_LARGE",
                    )
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size == 0:
            raise ApiError("Uploaded PDF is empty.", error_code="EMPTY_UPLOAD")
        temporary.replace(destination)
        return digest.hexdigest(), size
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
