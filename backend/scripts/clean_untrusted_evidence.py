import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import get_settings


FAKE_EVIDENCE_PATTERN = re.compile(
    r"fallback-support-paper-|"
    r"(?<![A-Za-z0-9])arxiv-\d+(?![\d.])|"
    r"arXiv study on .+?#\d+|"
    r"local uploaded paper context|"
    r"测试论文-[12]",
    flags=re.IGNORECASE,
)
AUDITED_TABLES = ("papers", "chunks", "gaps", "experiments")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_snapshot(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    if not _table_exists(conn, table):
        return {"count": 0, "sha256": hashlib.sha256(b"[]").hexdigest()}
    rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()]
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return {"count": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}


def _snapshot(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {table: _table_snapshot(conn, table) for table in AUDITED_TABLES}


def _row_evidence_text(row: sqlite3.Row, fields: tuple[str, ...]) -> str:
    values: list[str] = []
    available = set(row.keys())
    for field in fields:
        if field not in available:
            continue
        raw = row[field]
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            parsed = raw
        values.append(json.dumps(parsed, ensure_ascii=False, default=str))
    return "\n".join(values)


def _suspect_rows(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[str, str]]:
    gaps: dict[str, str] = {}
    experiments: dict[str, str] = {}
    if _table_exists(conn, "gaps"):
        for row in conn.execute("SELECT * FROM gaps").fetchall():
            text = _row_evidence_text(row, ("evidence_papers", "evidence_refs"))
            match = FAKE_EVIDENCE_PATTERN.search(text)
            if match:
                gaps[str(row["gap_id"])] = match.group(0)
    if _table_exists(conn, "experiments"):
        for row in conn.execute("SELECT * FROM experiments").fetchall():
            text = _row_evidence_text(row, ("support_papers", "support_refs"))
            match = FAKE_EVIDENCE_PATTERN.search(text)
            if match:
                experiments[str(row["experiment_id"])] = match.group(0)
            elif str(row["gap_id"]) in gaps:
                experiments[str(row["experiment_id"])] = f"parent gap {row['gap_id']} was removed"
    return gaps, experiments


def _ensure_trust_columns(conn: sqlite3.Connection) -> None:
    declarations = {
        "gaps": (
            ("evidence_refs", "TEXT NOT NULL DEFAULT '[]'"),
            ("trust_status", "TEXT NOT NULL DEFAULT 'legacy_unverified'"),
        ),
        "experiments": (
            ("support_refs", "TEXT NOT NULL DEFAULT '[]'"),
            ("trust_status", "TEXT NOT NULL DEFAULT 'legacy_unverified'"),
        ),
    }
    for table, columns in declarations.items():
        if not _table_exists(conn, table):
            continue
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, declaration in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _backup_database(source: Path, timestamp: str) -> Path:
    backup_path = source.with_name(f"{source.name}.backup-{timestamp}")
    with sqlite3.connect(source) as source_conn, sqlite3.connect(backup_path) as backup_conn:
        source_conn.backup(backup_conn)
    return backup_path


def clean_database(path: Path, apply: bool = False) -> dict[str, Any]:
    """Audit and optionally remove deterministic fake evidence from one SQLite database."""
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"SQLite database not found: {resolved}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path: Path | None = _backup_database(resolved, timestamp) if apply else None

    with sqlite3.connect(resolved) as conn:
        conn.row_factory = sqlite3.Row
        before = _snapshot(conn)
        removed_gaps, removed_experiments = _suspect_rows(conn)
        if apply:
            _ensure_trust_columns(conn)
            if removed_experiments:
                placeholders = ",".join("?" for _ in removed_experiments)
                conn.execute(
                    f"DELETE FROM experiments WHERE experiment_id IN ({placeholders})",
                    list(removed_experiments),
                )
            if removed_gaps:
                placeholders = ",".join("?" for _ in removed_gaps)
                conn.execute(
                    f"DELETE FROM gaps WHERE gap_id IN ({placeholders})",
                    list(removed_gaps),
                )
            conn.commit()
        after = _snapshot(conn)
        isolated_gaps = []
        isolated_experiments = []
        if apply and _table_exists(conn, "gaps"):
            isolated_gaps = [
                str(row["gap_id"])
                for row in conn.execute(
                    "SELECT gap_id FROM gaps WHERE trust_status = 'legacy_unverified' ORDER BY gap_id"
                ).fetchall()
            ]
        if apply and _table_exists(conn, "experiments"):
            isolated_experiments = [
                str(row["experiment_id"])
                for row in conn.execute(
                    "SELECT experiment_id FROM experiments WHERE trust_status = 'legacy_unverified' ORDER BY experiment_id"
                ).fetchall()
            ]

    report = {
        "mode": "apply" if apply else "dry-run",
        "database": str(resolved),
        "backup": str(backup_path) if backup_path else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "before": before,
        "after": after,
        "deleted_gaps": removed_gaps,
        "deleted_experiments": removed_experiments,
        "isolated_legacy_gaps": isolated_gaps,
        "isolated_legacy_experiments": isolated_experiments,
    }
    report_path = resolved.with_name(f"evidence-cleanup-{timestamp}.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up, audit, and clean deterministic fake evidence.")
    parser.add_argument("--apply", action="store_true", help="Back up the database and delete confirmed fake rows.")
    parser.add_argument("--database", type=Path, help="SQLite database path; defaults to the configured application DB.")
    args = parser.parse_args()
    database = args.database or get_settings().sqlite_path
    result = clean_database(database, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
