"""Back up and quarantine the confirmed legacy/test dataset.

The command is deliberately dry-run by default.  Apply mode refuses to mutate
the database unless the audited row counts match the approved cleanup scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import get_settings


CONFIRMED_TEST_DATE = "2026-07-19"
EXPECTED_TEST_PAPERS = 14
EXPECTED_LEGACY_GAPS = 21
EXPECTED_LEGACY_EXPERIMENTS = 6


def _rows(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _hash_rows(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _audit(conn: sqlite3.Connection) -> dict[str, Any]:
    papers = _rows(
        conn,
        """
        SELECT * FROM papers
        WHERE substr(created_at, 1, 10) = ?
        ORDER BY doc_id
        """,
        (CONFIRMED_TEST_DATE,),
    )
    doc_ids = [str(row["doc_id"]) for row in papers]
    if doc_ids:
        placeholders = ",".join("?" for _ in doc_ids)
        chunks = _rows(
            conn,
            f"SELECT * FROM chunks WHERE doc_id IN ({placeholders}) ORDER BY doc_id, chunk_id",
            tuple(doc_ids),
        )
    else:
        chunks = []
    gap_filter = (
        "WHERE trust_status = 'legacy_unverified'"
        if _column_exists(conn, "gaps", "trust_status")
        else ""
    )
    experiment_filter = (
        "WHERE trust_status = 'legacy_unverified'"
        if _column_exists(conn, "experiments", "trust_status")
        else ""
    )
    gaps = _rows(conn, f"SELECT * FROM gaps {gap_filter} ORDER BY gap_id")
    experiments = _rows(
        conn,
        f"SELECT * FROM experiments {experiment_filter} ORDER BY experiment_id",
    )
    retained = _rows(
        conn,
        """
        SELECT * FROM papers
        WHERE substr(created_at, 1, 10) <> ?
        ORDER BY doc_id
        """,
        (CONFIRMED_TEST_DATE,),
    )
    return {
        "test_papers": {
            "count": len(papers),
            "sha256": _hash_rows(papers),
            "doc_ids": doc_ids,
        },
        "test_chunks": {
            "count": len(chunks),
            "sha256": _hash_rows(chunks),
        },
        "legacy_gaps": {
            "count": len(gaps),
            "sha256": _hash_rows(gaps),
            "ids": [str(row["gap_id"]) for row in gaps],
        },
        "legacy_experiments": {
            "count": len(experiments),
            "sha256": _hash_rows(experiments),
            "ids": [str(row["experiment_id"]) for row in experiments],
        },
        "retained_papers": {
            "count": len(retained),
            "sha256": _hash_rows(retained),
            "doc_ids": [str(row["doc_id"]) for row in retained],
        },
    }


def _validate_approved_scope(audit: dict[str, Any]) -> None:
    actual = (
        audit["test_papers"]["count"],
        audit["legacy_gaps"]["count"],
        audit["legacy_experiments"]["count"],
        audit["retained_papers"]["count"],
    )
    expected = (
        EXPECTED_TEST_PAPERS,
        EXPECTED_LEGACY_GAPS,
        EXPECTED_LEGACY_EXPERIMENTS,
        4,
    )
    if actual != expected:
        raise RuntimeError(
            "Cleanup scope does not match the approved 14/21/6/4 counts: "
            f"found papers/gaps/experiments/retained={actual}."
        )


def _backup_database(source: Path, destination: Path) -> None:
    with sqlite3.connect(source) as source_conn, sqlite3.connect(destination) as backup_conn:
        source_conn.backup(backup_conn)


def _ensure_hardening_schema(conn: sqlite3.Connection) -> None:
    paper_columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(papers)").fetchall()
    }
    if "ingestion_status" not in paper_columns:
        conn.execute(
            "ALTER TABLE papers ADD COLUMN ingestion_status TEXT NOT NULL DEFAULT 'ready'"
        )
    if "reupload_required" not in paper_columns:
        conn.execute(
            "ALTER TABLE papers ADD COLUMN reupload_required INTEGER NOT NULL DEFAULT 0"
        )
    if "updated_at" not in paper_columns:
        conn.execute("ALTER TABLE papers ADD COLUMN updated_at TEXT")
    if not _column_exists(conn, "gaps", "trust_status"):
        conn.execute(
            "ALTER TABLE gaps ADD COLUMN trust_status TEXT NOT NULL DEFAULT 'legacy_unverified'"
        )
    if not _column_exists(conn, "experiments", "trust_status"):
        conn.execute(
            "ALTER TABLE experiments ADD COLUMN trust_status TEXT NOT NULL DEFAULT 'legacy_unverified'"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archived_gaps AS
        SELECT *, CAST(NULL AS TEXT) AS archived_at,
                  CAST(NULL AS TEXT) AS archive_reason
        FROM gaps WHERE 0
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archived_experiments AS
        SELECT *, CAST(NULL AS TEXT) AS archived_at,
                  CAST(NULL AS TEXT) AS archive_reason
        FROM experiments WHERE 0
        """
    )


def harden_legacy_data(
    database: Path,
    chroma_dir: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Audit or apply the explicitly approved legacy-data quarantine."""
    database = database.resolve()
    chroma_dir = chroma_dir.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"SQLite database not found: {database}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    database_backup = database.with_name(f"{database.name}.hardening-backup-{timestamp}")
    chroma_backup = chroma_dir.with_name(f"{chroma_dir.name}.hardening-backup-{timestamp}")

    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        audit = _audit(conn)
    _validate_approved_scope(audit)

    result: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": str(database),
        "chroma_dir": str(chroma_dir),
        "approved_scope": {
            "test_paper_date": CONFIRMED_TEST_DATE,
            "test_papers": EXPECTED_TEST_PAPERS,
            "legacy_gaps": EXPECTED_LEGACY_GAPS,
            "legacy_experiments": EXPECTED_LEGACY_EXPERIMENTS,
            "retained_papers": 4,
        },
        "audit": audit,
        "database_backup": None,
        "chroma_backup": None,
    }
    if apply:
        _backup_database(database, database_backup)
        if chroma_dir.exists():
            shutil.copytree(chroma_dir, chroma_backup)
        result["database_backup"] = str(database_backup)
        result["chroma_backup"] = str(chroma_backup) if chroma_dir.exists() else None
        now = datetime.now(timezone.utc).isoformat()
        doc_ids = audit["test_papers"]["doc_ids"]
        with sqlite3.connect(database) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            _ensure_hardening_schema(conn)
            conn.execute(
                """
                INSERT INTO archived_gaps
                SELECT *, ?, 'legacy_unverified: pre-hardening history'
                FROM gaps WHERE trust_status = 'legacy_unverified'
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO archived_experiments
                SELECT *, ?, 'legacy_unverified: pre-hardening history'
                FROM experiments WHERE trust_status = 'legacy_unverified'
                """,
                (now,),
            )
            conn.execute("DELETE FROM gaps WHERE trust_status = 'legacy_unverified'")
            conn.execute(
                "DELETE FROM experiments WHERE trust_status = 'legacy_unverified'"
            )
            placeholders = ",".join("?" for _ in doc_ids)
            if _table_exists(conn, "vector_index_entries"):
                conn.execute(
                    f"""
                    DELETE FROM vector_index_entries
                    WHERE chunk_id IN (
                        SELECT chunk_id FROM chunks WHERE doc_id IN ({placeholders})
                    )
                    """,
                    tuple(doc_ids),
                )
            conn.execute(
                f"DELETE FROM chunks WHERE doc_id IN ({placeholders})",
                tuple(doc_ids),
            )
            conn.execute(
                f"DELETE FROM papers WHERE doc_id IN ({placeholders})",
                tuple(doc_ids),
            )
            conn.execute(
                """
                UPDATE papers SET ingestion_status = 'reupload_required',
                    reupload_required = 1, updated_at = ?
                """,
                (now,),
            )
            conn.commit()
        with sqlite3.connect(database) as conn:
            conn.row_factory = sqlite3.Row
            result["after"] = {
                "papers": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
                "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "gaps": conn.execute("SELECT COUNT(*) FROM gaps").fetchone()[0],
                "experiments": conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0],
                "archived_gaps": conn.execute(
                    "SELECT COUNT(*) FROM archived_gaps"
                ).fetchone()[0],
                "archived_experiments": conn.execute(
                    "SELECT COUNT(*) FROM archived_experiments"
                ).fetchone()[0],
                "reupload_required": conn.execute(
                    "SELECT COUNT(*) FROM papers WHERE reupload_required = 1"
                ).fetchone()[0],
            }

    report_path = database.with_name(f"legacy-hardening-{timestamp}.json")
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["report"] = str(report_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Back up and quarantine the approved CS Gap Assist legacy dataset."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--chroma-dir", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    result = harden_legacy_data(
        args.database or settings.sqlite_path,
        args.chroma_dir or Path(settings.chroma_dir),
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
