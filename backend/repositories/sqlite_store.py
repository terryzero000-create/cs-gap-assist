import json
import math
import os
import re
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from backend.models.schemas import (
    EvidenceRef,
    ExperimentPlan,
    GapItem,
    NoteCreateRequest,
    NoteRecord,
    PaperChunk,
    PaperRecord,
)


class _ClosingSQLiteConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3 and release the Windows file handle."""

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class SQLiteStore:
    """SQLite-backed metadata repository for papers, gaps, experiments, tags, and notes."""

    def __init__(self, path: Path) -> None:
        """Create a repository and initialize tables."""
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with row mapping enabled."""
        conn = sqlite3.connect(self.path, factory=_ClosingSQLiteConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Create database tables if they do not exist."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    doc_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL DEFAULT '[]',
                    active_revision_id TEXT,
                    ingestion_status TEXT NOT NULL DEFAULT 'ready',
                    reupload_required INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    revision_id TEXT,
                    ordinal INTEGER NOT NULL DEFAULT 0,
                    page_end INTEGER,
                    section_path TEXT NOT NULL DEFAULT '',
                    char_start INTEGER NOT NULL DEFAULT 0,
                    char_end INTEGER NOT NULL DEFAULT 0,
                    block_type TEXT NOT NULL DEFAULT 'text',
                    chunker_version TEXT NOT NULL DEFAULT 'legacy',
                    content_hash TEXT NOT NULL DEFAULT '',
                    injection_flagged INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS paper_revisions (
                    revision_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    page_count INTEGER,
                    status TEXT NOT NULL,
                    chunker_version TEXT,
                    embedding_profile_key TEXT,
                    error_code TEXT,
                    error_detail TEXT,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_uploads (
                    upload_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    doc_id TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_detail TEXT,
                    warning_codes TEXT NOT NULL DEFAULT '[]',
                    warnings TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gaps (
                    gap_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    value_level TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence_papers TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    trust_status TEXT NOT NULL DEFAULT 'legacy_unverified',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    gap_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    datasets TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    baselines TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    risks TEXT NOT NULL,
                    support_papers TEXT NOT NULL,
                    support_refs TEXT NOT NULL DEFAULT '[]',
                    trust_status TEXT NOT NULL DEFAULT 'legacy_unverified'
                );
                CREATE TABLE IF NOT EXISTS notes (
                    note_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    related_doc_id TEXT,
                    related_gap_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vector_index_entries (
                    chunk_id TEXT NOT NULL,
                    profile_key TEXT NOT NULL,
                    collection_name TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chunk_id, profile_key)
                );
                CREATE TABLE IF NOT EXISTS vector_index_state (
                    profile_key TEXT PRIMARY KEY,
                    active_collection TEXT,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vector_index_migrations (
                    migration_id TEXT PRIMARY KEY,
                    profile_key TEXT NOT NULL,
                    source_collection TEXT NOT NULL,
                    target_collection TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS vector_index_locks (
                    lock_name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    acquired_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_metrics (
                    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    labels TEXT NOT NULL DEFAULT '{}',
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS operational_metrics_name_time
                    ON operational_metrics(name, recorded_at);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    doc_id UNINDEXED,
                    text,
                    tokenize='trigram'
                );
                CREATE TRIGGER IF NOT EXISTS chunks_fts_insert AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(chunk_id, doc_id, text)
                    VALUES (new.chunk_id, new.doc_id, new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_fts_delete AFTER DELETE ON chunks BEGIN
                    DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_fts_update AFTER UPDATE ON chunks BEGIN
                    DELETE FROM chunks_fts WHERE chunk_id = old.chunk_id;
                    INSERT INTO chunks_fts(chunk_id, doc_id, text)
                    VALUES (new.chunk_id, new.doc_id, new.text);
                END;
                """
            )
            self._ensure_column(conn, "gaps", "evidence_refs", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "gaps", "trust_status", "TEXT NOT NULL DEFAULT 'legacy_unverified'")
            self._ensure_column(conn, "experiments", "support_refs", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "experiments", "trust_status", "TEXT NOT NULL DEFAULT 'legacy_unverified'")
            self._ensure_column(conn, "papers", "active_revision_id", "TEXT")
            self._ensure_column(conn, "papers", "ingestion_status", "TEXT NOT NULL DEFAULT 'ready'")
            self._ensure_column(conn, "papers", "reupload_required", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "papers", "updated_at", "TEXT")
            self._ensure_column(conn, "chunks", "revision_id", "TEXT")
            self._ensure_column(conn, "chunks", "ordinal", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "chunks", "page_end", "INTEGER")
            self._ensure_column(conn, "chunks", "section_path", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "chunks", "char_start", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "chunks", "char_end", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "chunks", "block_type", "TEXT NOT NULL DEFAULT 'text'")
            self._ensure_column(conn, "chunks", "chunker_version", "TEXT NOT NULL DEFAULT 'legacy'")
            self._ensure_column(conn, "chunks", "content_hash", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "chunks", "injection_flagged", "INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                INSERT INTO chunks_fts(chunk_id, doc_id, text)
                SELECT c.chunk_id, c.doc_id, c.text
                FROM chunks c
                WHERE NOT EXISTS (
                    SELECT 1 FROM chunks_fts f WHERE f.chunk_id = c.chunk_id
                )
                """
            )

    def record_metric(
        self,
        name: str,
        value: float,
        unit: str,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record one aggregate operational measurement without request content."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO operational_metrics(name, value, unit, labels, recorded_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name,
                    float(value),
                    unit,
                    json.dumps(labels or {}, sort_keys=True),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def metric_summary(self, limit_per_metric: int = 1000) -> list[dict[str, object]]:
        """Return count/average/P95 summaries without exposing stored text or secrets."""
        with self._connect() as conn:
            names = [
                str(row["name"])
                for row in conn.execute(
                    "SELECT DISTINCT name FROM operational_metrics ORDER BY name"
                ).fetchall()
            ]
            summaries: list[dict[str, object]] = []
            for name in names:
                rows = conn.execute(
                    """
                    SELECT value, unit FROM operational_metrics
                    WHERE name = ? ORDER BY metric_id DESC LIMIT ?
                    """,
                    (name, limit_per_metric),
                ).fetchall()
                values = sorted(float(row["value"]) for row in rows)
                if not values:
                    continue
                p95_index = min(
                    len(values) - 1,
                    max(0, math.ceil(0.95 * len(values)) - 1),
                )
                summaries.append(
                    {
                        "name": name,
                        "count": len(values),
                        "average": sum(values) / len(values),
                        "p95": values[p95_index],
                        "unit": str(rows[0]["unit"]),
                    }
                )
        return summaries

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        """Add one backward-compatible SQLite column when an older database lacks it."""
        columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def add_paper(
        self,
        doc_id: str,
        title: str,
        chunks: list[PaperChunk],
        tags: list[str] | None = None,
        is_favorite: bool = False,
    ) -> PaperRecord:
        """Persist paper metadata and extracted chunks."""
        created_at = datetime.now(timezone.utc).isoformat()
        stored_tags = tags or []
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO papers
                    (doc_id, title, created_at, is_favorite, tags, ingestion_status, reupload_required, updated_at)
                VALUES (?, ?, ?, ?, ?, 'ready', 0, ?)
                """,
                (doc_id, title, created_at, int(is_favorite), json.dumps(stored_tags), created_at),
            )
            conn.executemany(
                """
                INSERT OR REPLACE INTO chunks
                    (chunk_id, doc_id, page, text, revision_id, ordinal, page_end, section_path,
                     char_start, char_end, block_type, chunker_version, content_hash, injection_flagged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._chunk_values(chunk) for chunk in chunks],
            )
        return PaperRecord(doc_id=doc_id, title=title, created_at=created_at, is_favorite=is_favorite, tags=stored_tags)

    def update_paper_collection(self, doc_id: str, tags: list[str], is_favorite: bool) -> PaperRecord:
        """Update collection metadata for a stored paper."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE papers SET tags = ?, is_favorite = ? WHERE doc_id = ?",
                (json.dumps(tags), int(is_favorite), doc_id),
            )
            row = conn.execute("SELECT * FROM papers WHERE doc_id = ?", (doc_id,)).fetchone()
        if row is None:
            raise KeyError(f"Paper not found: {doc_id}")
        return self._paper_from_row(row)

    def list_papers(self) -> list[PaperRecord]:
        """Return only active or explicitly retained papers, never staged placeholders."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM papers
                WHERE ingestion_status IN ('ready', 'reupload_required')
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._paper_from_row(row) for row in rows]

    def get_paper(self, doc_id: str) -> PaperRecord | None:
        """Return one stored paper by document id."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM papers WHERE doc_id = ?", (doc_id,)).fetchone()
        return self._paper_from_row(row) if row else None

    def paper_deletion_manifest(self, doc_id: str) -> dict[str, object] | None:
        """Return resources belonging to a paper after rejecting active ingestion."""
        with self._connect() as conn:
            paper = conn.execute(
                "SELECT doc_id FROM papers WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            if paper is None:
                return None
            active_upload = conn.execute(
                """
                SELECT upload_id FROM paper_uploads
                WHERE doc_id = ? AND status NOT IN ('ready', 'failed')
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
            if active_upload is not None:
                raise ValueError("PAPER_INGESTION_IN_PROGRESS")
            chunk_ids = [
                str(row["chunk_id"])
                for row in conn.execute(
                    "SELECT chunk_id FROM chunks WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
            ]
            source_paths = [
                str(row["source_path"])
                for row in conn.execute(
                    "SELECT source_path FROM paper_revisions WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
            ]
            vector_collections: list[str] = []
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                vector_collections = [
                    str(row["collection_name"])
                    for row in conn.execute(
                        f"""
                        SELECT DISTINCT collection_name
                        FROM vector_index_entries
                        WHERE chunk_id IN ({placeholders})
                        """,
                        chunk_ids,
                    ).fetchall()
                ]
        return {
            "doc_id": doc_id,
            "chunk_ids": chunk_ids,
            "source_paths": source_paths,
            "vector_collections": vector_collections,
        }

    def delete_paper_records(self, doc_id: str) -> dict[str, int]:
        """Atomically delete one paper and its durable database records."""
        with self._connect() as conn:
            paper = conn.execute(
                "SELECT doc_id FROM papers WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
            if paper is None:
                raise KeyError(f"Paper not found: {doc_id}")
            active_upload = conn.execute(
                """
                SELECT upload_id FROM paper_uploads
                WHERE doc_id = ? AND status NOT IN ('ready', 'failed')
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
            if active_upload is not None:
                raise ValueError("PAPER_INGESTION_IN_PROGRESS")
            chunk_ids = [
                str(row["chunk_id"])
                for row in conn.execute(
                    "SELECT chunk_id FROM chunks WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
            ]
            revision_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM paper_revisions WHERE doc_id = ?",
                    (doc_id,),
                ).fetchone()["count"]
            )
            upload_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM paper_uploads WHERE doc_id = ?",
                    (doc_id,),
                ).fetchone()["count"]
            )
            detached_notes = conn.execute(
                "UPDATE notes SET related_doc_id = NULL WHERE related_doc_id = ?",
                (doc_id,),
            ).rowcount
            unavailable_gap_refs = self._mark_deleted_evidence_refs(
                conn,
                table="gaps",
                id_column="gap_id",
                refs_column="evidence_refs",
                doc_id=doc_id,
            )
            unavailable_experiment_refs = self._mark_deleted_evidence_refs(
                conn,
                table="experiments",
                id_column="experiment_id",
                refs_column="support_refs",
                doc_id=doc_id,
            )
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                conn.execute(
                    f"DELETE FROM vector_index_entries WHERE chunk_id IN ({placeholders})",
                    chunk_ids,
                )
            conn.execute("DELETE FROM paper_uploads WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM paper_revisions WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM papers WHERE doc_id = ?", (doc_id,))
        return {
            "deleted_chunk_count": len(chunk_ids),
            "deleted_revision_count": revision_count,
            "deleted_upload_count": upload_count,
            "detached_note_count": max(detached_notes, 0),
            "unavailable_gap_ref_count": unavailable_gap_refs,
            "unavailable_experiment_ref_count": unavailable_experiment_refs,
        }

    @staticmethod
    def _mark_deleted_evidence_refs(
        conn: sqlite3.Connection,
        *,
        table: str,
        id_column: str,
        refs_column: str,
        doc_id: str,
    ) -> int:
        """Retain history while making references to a deleted local paper unusable."""
        marked = 0
        rows = conn.execute(
            f"SELECT {id_column}, {refs_column} FROM {table}"
        ).fetchall()
        for row in rows:
            try:
                refs = json.loads(row[refs_column])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(refs, list):
                continue
            changed = False
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                if (
                    ref.get("source") == "local"
                    and ref.get("doc_id") == doc_id
                    and ref.get("is_available", True)
                ):
                    ref["is_available"] = False
                    ref["unavailable_reason"] = "source_deleted"
                    marked += 1
                    changed = True
            if changed:
                conn.execute(
                    f"UPDATE {table} SET {refs_column} = ? WHERE {id_column} = ?",
                    (json.dumps(refs), row[id_column]),
                )
        return marked

    def list_chunks(self, doc_ids: list[str] | None = None) -> list[PaperChunk]:
        """Return stored paper chunks, optionally filtered by document ids."""
        conditions = [
            "(c.revision_id IS NULL OR c.revision_id = p.active_revision_id)",
            "p.ingestion_status = 'ready'",
        ]
        params: list[str] = []
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            conditions.append(f"c.doc_id IN ({placeholders})")
            params.extend(doc_ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.* FROM chunks c
                JOIN papers p ON p.doc_id = c.doc_id
                WHERE {' AND '.join(conditions)}
                ORDER BY c.doc_id, c.ordinal, c.page
                """,
                params,
            ).fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def count_chunks(self) -> int:
        """Return the number of SQLite source chunks."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS chunk_count
                FROM chunks c
                JOIN papers p ON p.doc_id = c.doc_id
                WHERE (c.revision_id IS NULL OR c.revision_id = p.active_revision_id)
                  AND p.ingestion_status = 'ready'
                """
            ).fetchone()
        return int(row["chunk_count"]) if row else 0

    def active_chunk_ids(self) -> set[str]:
        """Return active source chunk IDs without loading stored paper text."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.chunk_id
                FROM chunks c
                JOIN papers p ON p.doc_id = c.doc_id
                WHERE (c.revision_id IS NULL OR c.revision_id = p.active_revision_id)
                  AND p.ingestion_status = 'ready'
                """
            ).fetchall()
        return {str(row["chunk_id"]) for row in rows}

    def ping(self) -> None:
        """Verify that the configured SQLite database accepts a lightweight query."""
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()

    def count_reupload_required(self) -> int:
        """Return the number of legacy papers waiting for a trusted re-upload."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS paper_count
                FROM papers
                WHERE ingestion_status = 'reupload_required'
                   OR reupload_required = 1
                """
            ).fetchone()
        return int(row["paper_count"]) if row else 0

    def search_chunks_fts(
        self,
        query: str,
        doc_ids: list[str],
        limit: int = 30,
    ) -> list[PaperChunk]:
        """Return active chunks ranked by SQLite FTS5 BM25."""
        match_query = self._fts_query(query)
        if not match_query or not doc_ids:
            return []
        placeholders = ",".join("?" for _ in doc_ids)
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT c.*, bm25(chunks_fts) AS bm25_rank
                    FROM chunks_fts
                    JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
                    JOIN papers p ON p.doc_id = c.doc_id
                    WHERE chunks_fts MATCH ?
                      AND c.doc_id IN ({placeholders})
                      AND (c.revision_id IS NULL OR c.revision_id = p.active_revision_id)
                      AND p.ingestion_status = 'ready'
                    ORDER BY bm25_rank
                    LIMIT ?
                    """,
                    [match_query, *doc_ids, limit],
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            self._chunk_from_row(row).model_copy(
                update={"score": 1.0 / (1.0 + abs(float(row["bm25_rank"])))}
            )
            for row in rows
        ]

    def search_knowledge_chunks(
        self,
        query: str,
        *,
        tag: str | None = None,
        favorites_only: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[PaperChunk]:
        """Search active chunks in SQLite without materializing the full corpus."""
        safe_limit = max(1, min(limit, 50))
        safe_offset = max(0, offset)
        conditions = [
            "(c.revision_id IS NULL OR c.revision_id = p.active_revision_id)",
            "p.ingestion_status = 'ready'",
        ]
        filter_params: list[object] = []
        if tag:
            conditions.append(
                "EXISTS (SELECT 1 FROM json_each(p.tags) WHERE json_each.value = ?)"
            )
            filter_params.append(tag)
        if favorites_only:
            conditions.append("p.is_favorite = 1")
        where = " AND ".join(conditions)
        normalized = query.strip()
        match_query = self._fts_query(normalized)
        if match_query:
            try:
                with self._connect() as conn:
                    rows = conn.execute(
                        f"""
                        SELECT c.*, bm25(chunks_fts) AS bm25_rank
                        FROM chunks_fts
                        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
                        JOIN papers p ON p.doc_id = c.doc_id
                        WHERE chunks_fts MATCH ? AND {where}
                        ORDER BY bm25_rank, c.doc_id, c.ordinal, c.page
                        LIMIT ? OFFSET ?
                        """,
                        [match_query, *filter_params, safe_limit, safe_offset],
                    ).fetchall()
                return [
                    self._chunk_from_row(row).model_copy(
                        update={"score": 1.0 / (1.0 + abs(float(row["bm25_rank"])))}
                    )
                    for row in rows
                ]
            except sqlite3.OperationalError:
                # A build without usable FTS5 still gets a bounded lexical path.
                pass
        if normalized:
            conditions.append("LOWER(c.text) LIKE ?")
            filter_params.append(f"%{normalized.lower()}%")
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*
                FROM chunks c
                JOIN papers p ON p.doc_id = c.doc_id
                WHERE {' AND '.join(conditions)}
                ORDER BY p.created_at DESC, c.doc_id, c.ordinal, c.page
                LIMIT ? OFFSET ?
                """,
                [*filter_params, safe_limit, safe_offset],
            ).fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def create_upload(
        self,
        *,
        upload_id: str,
        idempotency_key: str,
        doc_id: str,
        revision_id: str,
        title: str,
        content_sha256: str,
        source_path: str,
        mime_type: str,
        size_bytes: int,
    ) -> dict[str, object]:
        """Create a durable upload and revision without exposing staged content."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM paper_uploads WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                revision = conn.execute(
                    "SELECT content_sha256 FROM paper_revisions WHERE revision_id = ?",
                    (existing["revision_id"],),
                ).fetchone()
                if revision is None or revision["content_sha256"] != content_sha256:
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                return dict(existing)
            paper = conn.execute("SELECT doc_id FROM papers WHERE doc_id = ?", (doc_id,)).fetchone()
            if paper is None:
                conn.execute(
                    """
                    INSERT INTO papers
                        (doc_id, title, created_at, is_favorite, tags, active_revision_id,
                         ingestion_status, reupload_required, updated_at)
                    VALUES (?, ?, ?, 0, '[]', NULL, 'received', 0, ?)
                    """,
                    (doc_id, title, now, now),
                )
            conn.execute(
                """
                INSERT INTO paper_revisions
                    (revision_id, doc_id, content_sha256, source_path, mime_type, size_bytes,
                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'received', ?, ?)
                """,
                (revision_id, doc_id, content_sha256, source_path, mime_type, size_bytes, now, now),
            )
            conn.execute(
                """
                INSERT INTO paper_uploads
                    (upload_id, idempotency_key, doc_id, revision_id, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'received', ?, ?)
                """,
                (upload_id, idempotency_key, doc_id, revision_id, title, now, now),
            )
            row = conn.execute("SELECT * FROM paper_uploads WHERE upload_id = ?", (upload_id,)).fetchone()
        return dict(row)

    def get_upload(self, upload_id: str) -> dict[str, object] | None:
        """Return one durable upload joined with revision statistics."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT u.*, r.page_count, r.source_path, r.mime_type, r.size_bytes,
                       r.content_sha256, r.embedding_profile_key,
                       (SELECT COUNT(*) FROM chunks c WHERE c.revision_id = u.revision_id) AS chunk_count
                FROM paper_uploads u
                JOIN paper_revisions r ON r.revision_id = u.revision_id
                WHERE u.upload_id = ?
                """,
                (upload_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_upload_status(
        self,
        upload_id: str,
        status: str,
        *,
        retryable: bool = False,
        error_code: str | None = None,
        error_detail: str | None = None,
        page_count: int | None = None,
        warning_codes: list[str] | None = None,
        warnings: list[str] | None = None,
        embedding_profile_key: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        """Persist an upload/revision state transition."""
        allowed_transitions = {
            "received": {"validating"},
            "validating": {"parsed", "failed"},
            "parsed": {"chunked", "failed"},
            "chunked": {"embedding", "failed"},
            "embedding": {"indexed", "failed"},
            "indexed": {"ready", "failed"},
            "failed": {"received"},
            "ready": set(),
        }
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT doc_id, revision_id, status FROM paper_uploads WHERE upload_id = ?",
                (upload_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Upload not found: {upload_id}")
            current_status = str(row["status"])
            if (
                status != current_status
                and status not in allowed_transitions.get(current_status, set())
            ):
                raise ValueError(
                    f"Invalid upload transition: {current_status} -> {status}"
                )
            conn.execute(
                """
                UPDATE paper_uploads SET
                    status = ?, retryable = ?, error_code = ?, error_detail = ?,
                    warning_codes = COALESCE(?, warning_codes),
                    warnings = COALESCE(?, warnings),
                    attempts = attempts + ?,
                    updated_at = ?
                WHERE upload_id = ?
                """,
                (
                    status,
                    int(retryable),
                    error_code,
                    error_detail,
                    json.dumps(warning_codes) if warning_codes is not None else None,
                    json.dumps(warnings) if warnings is not None else None,
                    int(increment_attempt),
                    now,
                    upload_id,
                ),
            )
            conn.execute(
                """
                UPDATE paper_revisions SET
                    status = ?, retryable = ?, error_code = ?, error_detail = ?,
                    page_count = COALESCE(?, page_count),
                    embedding_profile_key = COALESCE(?, embedding_profile_key),
                    updated_at = ?
                WHERE revision_id = ?
                """,
                (
                    status,
                    int(retryable),
                    error_code,
                    error_detail,
                    page_count,
                    embedding_profile_key,
                    now,
                    row["revision_id"],
                ),
            )
            paper = conn.execute(
                "SELECT active_revision_id FROM papers WHERE doc_id = ?",
                (row["doc_id"],),
            ).fetchone()
            if paper is not None and paper["active_revision_id"] is None:
                conn.execute(
                    "UPDATE papers SET ingestion_status = ?, updated_at = ? WHERE doc_id = ?",
                    (status, now, row["doc_id"]),
                )

    def store_revision_chunks(self, revision_id: str, chunks: list[PaperChunk]) -> None:
        """Replace staged chunks for one non-active revision."""
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE revision_id = ?", (revision_id,))
            conn.executemany(
                """
                INSERT INTO chunks
                    (chunk_id, doc_id, page, text, revision_id, ordinal, page_end, section_path,
                     char_start, char_end, block_type, chunker_version, content_hash, injection_flagged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._chunk_values(chunk) for chunk in chunks],
            )

    def revision_chunk_ids(self, revision_id: str) -> list[str]:
        """Return exact chunk IDs belonging to one revision."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chunk_id FROM chunks WHERE revision_id = ? ORDER BY ordinal",
                (revision_id,),
            ).fetchall()
        return [str(row["chunk_id"]) for row in rows]

    def delete_revision_chunks(self, revision_id: str) -> None:
        """Delete inactive source chunks after their vectors are removed."""
        with self._connect() as conn:
            active = conn.execute(
                "SELECT 1 FROM papers WHERE active_revision_id = ?",
                (revision_id,),
            ).fetchone()
            if active:
                raise ValueError("Cannot delete active revision chunks.")
            conn.execute("DELETE FROM chunks WHERE revision_id = ?", (revision_id,))

    def failed_revision_cleanup_manifests(
        self,
        doc_id: str,
        *,
        exclude_revision_id: str,
    ) -> list[dict[str, object]]:
        """Return inactive failed revisions that a successful replacement may reclaim."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.revision_id, r.source_path
                FROM paper_revisions r
                LEFT JOIN papers p ON p.doc_id = r.doc_id
                WHERE r.doc_id = ?
                  AND r.revision_id != ?
                  AND r.status = 'failed'
                  AND (p.active_revision_id IS NULL OR p.active_revision_id != r.revision_id)
                ORDER BY r.created_at
                """,
                (doc_id, exclude_revision_id),
            ).fetchall()
            manifests: list[dict[str, object]] = []
            for row in rows:
                chunk_ids = [
                    str(chunk["chunk_id"])
                    for chunk in conn.execute(
                        "SELECT chunk_id FROM chunks WHERE revision_id = ? ORDER BY ordinal",
                        (row["revision_id"],),
                    ).fetchall()
                ]
                manifests.append(
                    {
                        "revision_id": str(row["revision_id"]),
                        "source_path": str(row["source_path"]),
                        "chunk_ids": chunk_ids,
                    }
                )
        return manifests

    def activate_upload(self, upload_id: str) -> str | None:
        """Atomically switch a fully indexed revision and return the previous revision."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            upload = conn.execute(
                "SELECT doc_id, revision_id, status FROM paper_uploads WHERE upload_id = ?",
                (upload_id,),
            ).fetchone()
            if upload is None:
                raise KeyError(f"Upload not found: {upload_id}")
            if upload["status"] != "indexed":
                raise ValueError("Only an indexed revision may become active.")
            paper = conn.execute(
                "SELECT active_revision_id FROM papers WHERE doc_id = ?",
                (upload["doc_id"],),
            ).fetchone()
            previous = str(paper["active_revision_id"]) if paper and paper["active_revision_id"] else None
            conn.execute(
                """
                UPDATE papers SET active_revision_id = ?, ingestion_status = 'ready',
                    reupload_required = 0, updated_at = ?
                WHERE doc_id = ?
                """,
                (upload["revision_id"], now, upload["doc_id"]),
            )
            conn.execute(
                "UPDATE paper_revisions SET status = 'ready', updated_at = ? WHERE revision_id = ?",
                (now, upload["revision_id"]),
            )
            conn.execute(
                """
                UPDATE paper_uploads SET status = 'ready', retryable = 0,
                    error_code = NULL, error_detail = NULL, updated_at = ?
                WHERE upload_id = ?
                """,
                (now, upload_id),
            )
        return previous

    def recover_interrupted_uploads(self) -> list[str]:
        """Mark process-interrupted uploads as retryable and return their IDs."""
        active = ("validating", "parsed", "chunked", "embedding", "indexed")
        placeholders = ",".join("?" for _ in active)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT upload_id FROM paper_uploads WHERE status IN ({placeholders})",
                active,
            ).fetchall()
            upload_ids = [str(row["upload_id"]) for row in rows]
            if upload_ids:
                now = datetime.now(timezone.utc).isoformat()
                ids = ",".join("?" for _ in upload_ids)
                conn.execute(
                    f"""
                    UPDATE paper_uploads SET status = 'failed', retryable = 1,
                        error_code = 'WORKER_INTERRUPTED',
                        error_detail = 'The ingestion worker stopped before completion.',
                        updated_at = ?
                    WHERE upload_id IN ({ids})
                    """,
                    [now, *upload_ids],
                )
                conn.execute(
                    f"""
                    UPDATE paper_revisions SET status = 'failed', retryable = 1,
                        error_code = 'WORKER_INTERRUPTED',
                        error_detail = 'The ingestion worker stopped before completion.',
                        updated_at = ?
                    WHERE revision_id IN (
                        SELECT revision_id FROM paper_uploads
                        WHERE upload_id IN ({ids})
                    )
                    """,
                    [now, *upload_ids],
                )
                conn.execute(
                    f"""
                    UPDATE papers SET ingestion_status = 'failed', updated_at = ?
                    WHERE active_revision_id IS NULL
                      AND doc_id IN (
                        SELECT doc_id FROM paper_uploads
                        WHERE upload_id IN ({ids})
                    )
                    """,
                    [now, *upload_ids],
                )
        return upload_ids

    def delete_vector_entries(self, chunk_ids: list[str], profile_key: str) -> None:
        """Remove bookkeeping for vectors deleted during reconciliation."""
        if not chunk_ids:
            return
        placeholders = ",".join("?" for _ in chunk_ids)
        with self._connect() as conn:
            conn.execute(
                f"""
                DELETE FROM vector_index_entries
                WHERE profile_key = ? AND chunk_id IN ({placeholders})
                """,
                [profile_key, *chunk_ids],
            )

    def reset_upload_for_retry(self, upload_id: str) -> None:
        """Reset only retryable failed uploads to the received state."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT retryable, status FROM paper_uploads WHERE upload_id = ?",
                (upload_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Upload not found: {upload_id}")
            if row["status"] != "failed" or not bool(row["retryable"]):
                raise ValueError("UPLOAD_NOT_RETRYABLE")
        self.update_upload_status(upload_id, "received")

    def mark_vector_entries(
        self,
        chunks: list[PaperChunk],
        profile_key: str,
        collection_name: str,
        content_hashes: dict[str, str],
        status: str,
        error: str | None = None,
    ) -> None:
        """Upsert per-chunk vector indexing state."""
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO vector_index_entries
                    (chunk_id, profile_key, collection_name, content_hash, status, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id, profile_key) DO UPDATE SET
                    collection_name=excluded.collection_name,
                    content_hash=excluded.content_hash,
                    status=excluded.status,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                [
                    (
                        chunk.chunk_id,
                        profile_key,
                        collection_name,
                        content_hashes[chunk.chunk_id],
                        status,
                        error,
                        updated_at,
                    )
                    for chunk in chunks
                ],
            )

    def vector_entry_counts(self, profile_key: str) -> dict[str, int]:
        """Return vector entry counts grouped by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS total FROM vector_index_entries WHERE profile_key = ? GROUP BY status",
                (profile_key,),
            ).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    def set_vector_index_state(self, profile_key: str, state: str, active_collection: str | None) -> None:
        """Atomically record the collection used for one embedding profile."""
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vector_index_state (profile_key, active_collection, state, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_key) DO UPDATE SET
                    active_collection=excluded.active_collection,
                    state=excluded.state,
                    updated_at=excluded.updated_at
                """,
                (profile_key, active_collection, state, updated_at),
            )

    def get_vector_index_state(self, profile_key: str) -> dict[str, str | None] | None:
        """Return active collection state for a profile."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM vector_index_state WHERE profile_key = ?", (profile_key,)).fetchone()
        return dict(row) if row else None

    def acquire_vector_index_lock(self, owner: str) -> bool:
        """Acquire the local migration lock, recovering one left by a dead process."""
        acquired_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT owner FROM vector_index_locks WHERE lock_name = 'migration'"
            ).fetchone()
            if existing and self._lock_owner_is_alive(str(existing["owner"])):
                return False
            conn.execute("DELETE FROM vector_index_locks WHERE lock_name = 'migration'")
            conn.execute(
                "INSERT INTO vector_index_locks (lock_name, owner, acquired_at) VALUES ('migration', ?, ?)",
                (owner, acquired_at),
            )
        return True

    @staticmethod
    def _lock_owner_is_alive(owner: str) -> bool:
        """Return whether a PID-prefixed migration owner still exists."""
        try:
            pid = int(owner.split(":", 1)[0])
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except (OSError, ValueError):
            return False

    def release_vector_index_lock(self, owner: str) -> None:
        """Release a migration lock owned by the caller."""
        with self._connect() as conn:
            conn.execute("DELETE FROM vector_index_locks WHERE lock_name = 'migration' AND owner = ?", (owner,))

    def vector_index_lock(self) -> dict[str, str] | None:
        """Return current migration lock information."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM vector_index_locks WHERE lock_name = 'migration'").fetchone()
        return dict(row) if row else None

    def save_vector_migration(
        self,
        migration_id: str,
        profile_key: str,
        source_collection: str,
        target_collection: str,
        status: str,
        processed_count: int = 0,
        skipped_count: int = 0,
        failed_count: int = 0,
        error: str | None = None,
    ) -> None:
        """Create or update an idempotent vector migration run."""
        now = datetime.now(timezone.utc).isoformat()
        completed_at = now if status in {"complete", "failed"} else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vector_index_migrations
                    (migration_id, profile_key, source_collection, target_collection, status, started_at,
                     completed_at, processed_count, skipped_count, failed_count, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(migration_id) DO UPDATE SET
                    status=excluded.status,
                    completed_at=excluded.completed_at,
                    processed_count=excluded.processed_count,
                    skipped_count=excluded.skipped_count,
                    failed_count=excluded.failed_count,
                    error=excluded.error
                """,
                (
                    migration_id,
                    profile_key,
                    source_collection,
                    target_collection,
                    status,
                    now,
                    completed_at,
                    processed_count,
                    skipped_count,
                    failed_count,
                    error,
                ),
            )

    def latest_vector_migration(self, profile_key: str) -> dict[str, object] | None:
        """Return the most recent migration for a profile."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM vector_index_migrations WHERE profile_key = ? ORDER BY started_at DESC LIMIT 1",
                (profile_key,),
            ).fetchone()
        return dict(row) if row else None

    def save_gap(self, gap: GapItem) -> GapItem:
        """Persist a gap only when every evidence reference passes server-side validation."""
        if gap.trust_status not in {"verified", "local_only"}:
            raise ValueError("Only verified or local-only gaps may be persisted.")
        trusted_refs = self.trusted_evidence_refs(gap.evidence_refs)
        if not trusted_refs or len(trusted_refs) != len(gap.evidence_refs):
            raise ValueError("Gap evidence could not be verified.")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO gaps
                    (gap_id, title, value_level, description, evidence_papers, evidence_refs, trust_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gap.gap_id,
                    gap.title,
                    gap.value_level,
                    gap.description,
                    json.dumps([ref.id for ref in trusted_refs]),
                    json.dumps([ref.model_dump() for ref in trusted_refs]),
                    gap.trust_status,
                    gap.created_at,
                ),
            )
        return gap

    def list_gaps(self, include_unverified: bool = False) -> list[GapItem]:
        """Return stored gap results."""
        with self._connect() as conn:
            if include_unverified:
                rows = conn.execute("SELECT * FROM gaps ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gaps WHERE trust_status IN ('verified', 'local_only') ORDER BY created_at DESC"
                ).fetchall()
        return [
            GapItem(
                gap_id=row["gap_id"],
                title=row["title"],
                value_level=row["value_level"],
                description=row["description"],
                evidence_papers=json.loads(row["evidence_papers"]),
                evidence_refs=[EvidenceRef.model_validate(item) for item in json.loads(row["evidence_refs"])],
                trust_status=row["trust_status"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_experiment(self, experiment: ExperimentPlan) -> ExperimentPlan:
        """Persist a trusted experiment once, reusing an identical saved plan."""
        if experiment.trust_status not in {"verified", "local_only"}:
            raise ValueError("Only verified or local-only experiments may be persisted.")
        trusted_refs = self.trusted_evidence_refs(experiment.support_refs)
        if not trusted_refs or len(trusted_refs) != len(experiment.support_refs):
            raise ValueError("Experiment support evidence could not be verified.")
        normalized = experiment.model_copy(
            update={
                "support_papers": [ref.id for ref in trusted_refs],
                "support_refs": trusted_refs,
            }
        )
        with self._connect() as conn:
            existing_rows = conn.execute(
                "SELECT * FROM experiments WHERE gap_id = ?",
                (experiment.gap_id,),
            ).fetchall()
            for row in existing_rows:
                existing = self._experiment_from_row(row)
                if self._experiment_signature(existing) == self._experiment_signature(normalized):
                    return existing
            conn.execute(
                """
                INSERT OR REPLACE INTO experiments
                    (experiment_id, gap_id, objective, datasets, metrics, baselines, steps, risks,
                     support_papers, support_refs, trust_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized.experiment_id,
                    normalized.gap_id,
                    normalized.objective,
                    json.dumps(normalized.datasets),
                    json.dumps(normalized.metrics),
                    json.dumps(normalized.baselines),
                    json.dumps(normalized.steps),
                    json.dumps(normalized.risks),
                    json.dumps([ref.id for ref in trusted_refs]),
                    json.dumps([ref.model_dump() for ref in trusted_refs]),
                    normalized.trust_status,
                ),
            )
        return normalized

    def list_experiments(
        self,
        gap_id: str | None = None,
        include_unverified: bool = False,
    ) -> list[ExperimentPlan]:
        """Return stored experiment suggestion history."""
        conditions: list[str] = []
        params: list[str] = []
        if gap_id:
            conditions.append("gap_id = ?")
            params.append(gap_id)
        if not include_unverified:
            conditions.append("trust_status IN ('verified', 'local_only')")
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM experiments{where}", params).fetchall()
        return [self._experiment_from_row(row) for row in rows]

    @staticmethod
    def _experiment_from_row(row: sqlite3.Row) -> ExperimentPlan:
        return ExperimentPlan(
            experiment_id=row["experiment_id"],
            gap_id=row["gap_id"],
            objective=row["objective"],
            datasets=json.loads(row["datasets"]),
            metrics=json.loads(row["metrics"]),
            baselines=json.loads(row["baselines"]),
            steps=json.loads(row["steps"]),
            risks=json.loads(row["risks"]),
            support_papers=json.loads(row["support_papers"]),
            support_refs=[EvidenceRef.model_validate(item) for item in json.loads(row["support_refs"])],
            trust_status=row["trust_status"],
        )

    @staticmethod
    def _experiment_signature(experiment: ExperimentPlan) -> tuple[object, ...]:
        return (
            experiment.gap_id,
            experiment.objective,
            tuple(experiment.datasets),
            tuple(experiment.metrics),
            tuple(experiment.baselines),
            tuple(experiment.steps),
            tuple(experiment.risks),
            tuple(ref.model_dump_json() for ref in experiment.support_refs),
            experiment.trust_status,
        )

    def trusted_evidence_refs(self, refs: list[EvidenceRef]) -> list[EvidenceRef]:
        """Revalidate structured references immediately before persistence or reuse."""
        trusted: list[EvidenceRef] = []
        seen: set[str] = set()
        for ref in refs:
            if ref.id in seen:
                continue
            if not ref.is_available:
                continue
            if ref.source == "local":
                if not ref.doc_id or not ref.chunk_id or ref.page is None:
                    continue
                with self._connect() as conn:
                    row = conn.execute(
                        """
                        SELECT c.doc_id, c.page
                        FROM chunks c
                        JOIN papers p ON p.doc_id = c.doc_id
                        WHERE c.chunk_id = ?
                          AND (c.revision_id IS NULL OR c.revision_id = p.active_revision_id)
                          AND p.ingestion_status = 'ready'
                        """,
                        (ref.chunk_id,),
                    ).fetchone()
                if row is None or row["doc_id"] != ref.doc_id or int(row["page"]) != ref.page:
                    continue
            elif ref.source == "arxiv":
                arxiv_id = ref.id.removeprefix("arxiv-")
                if (
                    not ref.id.startswith("arxiv-")
                    or arxiv_id.isdigit()
                    or not re.fullmatch(r"[A-Za-z0-9./-]+", arxiv_id)
                    or "arxiv.org/abs/" not in ref.canonical_url
                ):
                    continue
            elif ref.source == "openalex":
                openalex_id = ref.id.removeprefix("openalex-")
                if not re.fullmatch(r"W\d+", openalex_id) or "openalex.org/" not in ref.canonical_url:
                    continue
            else:
                continue
            trusted.append(ref)
            seen.add(ref.id)
        return trusted

    def add_note(self, request: NoteCreateRequest) -> NoteRecord:
        """Persist a knowledge-base note."""
        note = NoteRecord(**request.model_dump())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    note.note_id,
                    note.title,
                    note.content,
                    json.dumps(note.tags),
                    note.related_doc_id,
                    note.related_gap_id,
                    note.created_at,
                ),
            )
        return note

    def list_notes(self, query: str | None = None) -> list[NoteRecord]:
        """Return notes, optionally filtered by title or content."""
        with self._connect() as conn:
            if query:
                pattern = f"%{query}%"
                rows = conn.execute(
                    "SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? ORDER BY created_at DESC",
                    (pattern, pattern),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()
        return [
            NoteRecord(
                note_id=row["note_id"],
                title=row["title"],
                content=row["content"],
                tags=json.loads(row["tags"]),
                related_doc_id=row["related_doc_id"],
                related_gap_id=row["related_gap_id"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _paper_from_row(self, row: sqlite3.Row) -> PaperRecord:
        """Convert a SQLite row into a paper record."""
        return PaperRecord(
            doc_id=row["doc_id"],
            title=row["title"],
            created_at=row["created_at"],
            is_favorite=bool(row["is_favorite"]),
            tags=json.loads(row["tags"]),
            active_revision_id=row["active_revision_id"],
            ingestion_status=row["ingestion_status"],
            reupload_required=bool(row["reupload_required"]),
        )

    @staticmethod
    def _fts_query(query: str) -> str:
        """Build a safe OR query for the trigram tokenizer."""
        tokens = re.findall(r"[A-Za-z0-9_]{3,}|[\u3400-\u9fff]{3,}", query)
        return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens[:32])

    @staticmethod
    def _chunk_values(chunk: PaperChunk) -> tuple[object, ...]:
        """Return the normalized SQLite tuple for a chunk."""
        return (
            chunk.chunk_id,
            chunk.doc_id,
            chunk.page,
            chunk.text,
            chunk.revision_id,
            chunk.ordinal,
            chunk.page_end,
            chunk.section_path,
            chunk.char_start,
            chunk.char_end,
            chunk.block_type,
            chunk.chunker_version,
            chunk.content_hash,
            int(chunk.injection_flagged),
        )

    @staticmethod
    def _chunk_from_row(row: sqlite3.Row) -> PaperChunk:
        """Convert one active chunk row into the API model."""
        return PaperChunk(
            chunk_id=row["chunk_id"],
            doc_id=row["doc_id"],
            page=row["page"],
            text=row["text"],
            revision_id=row["revision_id"],
            ordinal=row["ordinal"],
            page_end=row["page_end"],
            section_path=row["section_path"],
            char_start=row["char_start"],
            char_end=row["char_end"],
            block_type=row["block_type"],
            chunker_version=row["chunker_version"],
            content_hash=row["content_hash"],
            injection_flagged=bool(row["injection_flagged"]),
        )


@lru_cache(maxsize=32)
def get_sqlite_store(path: Path) -> SQLiteStore:
    """Return one process-local repository per resolved database path."""
    return SQLiteStore(path.resolve())
