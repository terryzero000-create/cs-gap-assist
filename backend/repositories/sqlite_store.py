import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.models.schemas import ExperimentPlan, GapItem, NoteCreateRequest, NoteRecord, PaperChunk, PaperRecord


class SQLiteStore:
    """SQLite-backed metadata repository for papers, gaps, experiments, tags, and notes."""

    def __init__(self, path: Path) -> None:
        """Create a repository and initialize tables."""
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with row mapping enabled."""
        conn = sqlite3.connect(self.path)
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
                    tags TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    page INTEGER NOT NULL,
                    text TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gaps (
                    gap_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    value_level TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence_papers TEXT NOT NULL,
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
                    support_papers TEXT NOT NULL
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
                """
            )

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
                "INSERT OR REPLACE INTO papers (doc_id, title, created_at, is_favorite, tags) VALUES (?, ?, ?, ?, ?)",
                (doc_id, title, created_at, int(is_favorite), json.dumps(stored_tags)),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO chunks (chunk_id, doc_id, page, text) VALUES (?, ?, ?, ?)",
                [(chunk.chunk_id, chunk.doc_id, chunk.page, chunk.text) for chunk in chunks],
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
        """Return stored papers ordered by creation time."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM papers ORDER BY created_at DESC").fetchall()
        return [self._paper_from_row(row) for row in rows]

    def get_paper(self, doc_id: str) -> PaperRecord | None:
        """Return one stored paper by document id."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM papers WHERE doc_id = ?", (doc_id,)).fetchone()
        return self._paper_from_row(row) if row else None

    def list_chunks(self, doc_ids: list[str] | None = None) -> list[PaperChunk]:
        """Return stored paper chunks, optionally filtered by document ids."""
        with self._connect() as conn:
            if doc_ids:
                placeholders = ",".join("?" for _ in doc_ids)
                rows = conn.execute(
                    f"SELECT * FROM chunks WHERE doc_id IN ({placeholders}) ORDER BY doc_id, page",
                    doc_ids,
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM chunks ORDER BY doc_id, page").fetchall()
        return [
            PaperChunk(chunk_id=row["chunk_id"], doc_id=row["doc_id"], page=row["page"], text=row["text"])
            for row in rows
        ]

    def count_chunks(self) -> int:
        """Return the number of SQLite source chunks."""
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

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
        """Persist a research gap result."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO gaps VALUES (?, ?, ?, ?, ?, ?)",
                (gap.gap_id, gap.title, gap.value_level, gap.description, json.dumps(gap.evidence_papers), gap.created_at),
            )
        return gap

    def list_gaps(self) -> list[GapItem]:
        """Return stored gap results."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM gaps ORDER BY created_at DESC").fetchall()
        return [
            GapItem(
                gap_id=row["gap_id"],
                title=row["title"],
                value_level=row["value_level"],
                description=row["description"],
                evidence_papers=json.loads(row["evidence_papers"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_experiment(self, experiment: ExperimentPlan) -> ExperimentPlan:
        """Persist an experiment suggestion history item."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    experiment.experiment_id,
                    experiment.gap_id,
                    experiment.objective,
                    json.dumps(experiment.datasets),
                    json.dumps(experiment.metrics),
                    json.dumps(experiment.baselines),
                    json.dumps(experiment.steps),
                    json.dumps(experiment.risks),
                    json.dumps(experiment.support_papers),
                ),
            )
        return experiment

    def list_experiments(self, gap_id: str | None = None) -> list[ExperimentPlan]:
        """Return stored experiment suggestion history."""
        with self._connect() as conn:
            if gap_id:
                rows = conn.execute("SELECT * FROM experiments WHERE gap_id = ?", (gap_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM experiments").fetchall()
        return [
            ExperimentPlan(
                experiment_id=row["experiment_id"],
                gap_id=row["gap_id"],
                objective=row["objective"],
                datasets=json.loads(row["datasets"]),
                metrics=json.loads(row["metrics"]),
                baselines=json.loads(row["baselines"]),
                steps=json.loads(row["steps"]),
                risks=json.loads(row["risks"]),
                support_papers=json.loads(row["support_papers"]),
            )
            for row in rows
        ]

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
        )
