import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.config import get_settings
from backend.models.schemas import PaperChunk
from backend.rag.vector_store import chunk_content_hash, clear_vector_store_cache, get_vector_store
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.vector_index import (
    LEGACY_COLLECTION,
    VectorIndexManager,
    configured_embedding_provider,
)


def _migration_id(profile_key: str, source: str, target: str) -> str:
    payload = f"{profile_key}|{source}|{target}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _target_is_current(target_store, chunk: PaperChunk, profile_key: str) -> bool:
    entry = target_store.get_entry(chunk.chunk_id)
    if not entry:
        return False
    metadata = entry.get("metadata") or {}
    return (
        metadata.get("content_hash") == chunk_content_hash(chunk)
        and metadata.get("profile_key") == profile_key
    )


def migration_plan(manager: VectorIndexManager) -> dict[str, Any]:
    """Return a read-only migration plan."""
    sqlite = manager.sqlite
    chunks = sqlite.list_chunks()
    source = get_vector_store(manager.settings, collection_name=LEGACY_COLLECTION, create_if_missing=False)
    target = get_vector_store(
        manager.settings,
        profile=manager.profile,
        collection_name=manager.profile.collection_name,
        create_if_missing=False,
    )
    current = sum(_target_is_current(target, chunk, manager.profile.key) for chunk in chunks)
    source_ids = source.ids()
    sqlite_ids = {chunk.chunk_id for chunk in chunks}
    manifest = [
        {
            "chunk_id": chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "revision_id": chunk.revision_id,
            "content_hash": chunk_content_hash(chunk),
            "chunker_version": chunk.chunker_version,
        }
        for chunk in chunks
    ]
    manifest_sha256 = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    reupload_required = [
        paper.doc_id for paper in sqlite.list_papers() if paper.reupload_required
    ]
    return {
        "mode": "dry-run",
        "profile_key": manager.profile.key,
        "source_collection": LEGACY_COLLECTION,
        "target_collection": manager.profile.collection_name,
        "sqlite_chunk_count": len(chunks),
        "already_current_count": current,
        "pending_count": len(chunks) - current,
        "legacy_vector_count": len(source_ids),
        "legacy_orphan_count": len(source_ids - sqlite_ids),
        "manifest_sha256": manifest_sha256,
        "manifest": manifest,
        "reupload_required_doc_ids": reupload_required,
    }


async def apply_migration(manager: VectorIndexManager) -> dict[str, Any]:
    """Apply or resume the deterministic migration without deleting legacy data."""
    sqlite = manager.sqlite
    reupload_required = [
        paper.doc_id for paper in sqlite.list_papers() if paper.reupload_required
    ]
    if reupload_required:
        return {
            "mode": "apply",
            "processed_count": 0,
            "skipped_count": 0,
            "failed_count": len(reupload_required),
            "missing_count": 0,
            "activated": False,
            "error_code": "SOURCE_PDF_REUPLOAD_REQUIRED",
            "reupload_required_doc_ids": reupload_required,
            "target_collection": manager.profile.collection_name,
        }
    profile = manager.profile
    source_name = LEGACY_COLLECTION
    target_name = profile.collection_name
    migration_id = _migration_id(profile.key, source_name, target_name)
    owner = f"{os.getpid()}:{migration_id}"
    if not sqlite.acquire_vector_index_lock(owner):
        raise RuntimeError("Another vector index migration is already in progress.")

    database_backup, chroma_backup = _migration_backups(
        manager.settings.sqlite_path,
        Path(manager.settings.chroma_dir),
    )
    processed = 0
    skipped = 0
    failed = 0
    target = get_vector_store(manager.settings, profile=profile, collection_name=target_name)
    provider = configured_embedding_provider(manager.settings, document=True)
    sqlite.save_vector_migration(migration_id, profile.key, source_name, target_name, "running")
    sqlite.set_vector_index_state(profile.key, "migrating", manager.collection_name())
    try:
        for chunk in sqlite.list_chunks():
            if _target_is_current(target, chunk, profile.key):
                skipped += 1
                continue
            result = await provider.embed([chunk.text])
            if result.is_fallback or not result.vectors or result.profile != profile:
                failed += 1
                sqlite.mark_vector_entries(
                    [chunk], profile.key, target_name, {chunk.chunk_id: chunk_content_hash(chunk)},
                    "failed", "Embedding provider returned fallback or an incompatible profile during migration.",
                )
                continue
            vector = result.vectors[0]
            try:
                target.add_chunks([chunk], [vector])
                sqlite.mark_vector_entries(
                    [chunk], profile.key, target_name, {chunk.chunk_id: chunk_content_hash(chunk)}, "ready"
                )
                processed += 1
            except Exception as exc:
                failed += 1
                sqlite.mark_vector_entries(
                    [chunk], profile.key, target_name, {chunk.chunk_id: chunk_content_hash(chunk)}, "failed", str(exc)
                )
            sqlite.save_vector_migration(
                migration_id, profile.key, source_name, target_name, "running", processed, skipped, failed
            )

        source_chunks = sqlite.list_chunks()
        missing = [
            chunk.chunk_id
            for chunk in source_chunks
            if not _target_is_current(target, chunk, profile.key)
        ]
        smoke_test = _retrieval_smoke_test(target, source_chunks)
        profile_matches = target.profile == profile
        if failed or missing or not smoke_test["passed"] or not profile_matches:
            failure_count = max(
                failed,
                len(missing),
                int(not smoke_test["passed"]),
                int(not profile_matches),
            )
            sqlite.save_vector_migration(
                migration_id,
                profile.key,
                source_name,
                target_name,
                "failed",
                processed,
                skipped,
                failure_count,
                (
                    f"{len(missing)} chunks are not current; "
                    f"profile_matches={profile_matches}; smoke_test={smoke_test['passed']}."
                ),
            )
            sqlite.set_vector_index_state(profile.key, "migration_required", manager.collection_name())
        else:
            sqlite.save_vector_migration(
                migration_id, profile.key, source_name, target_name, "complete", processed, skipped, 0
            )
            sqlite.set_vector_index_state(profile.key, "ready", target_name)
        clear_vector_store_cache()
        return {
            "mode": "apply",
            "migration_id": migration_id,
            "processed_count": processed,
            "skipped_count": skipped,
            "failed_count": max(
                failed,
                len(missing),
                int(not smoke_test["passed"]),
                int(not profile_matches),
            ),
            "missing_count": len(missing),
            "profile_matches": profile_matches,
            "smoke_test": smoke_test,
            "activated": not failed and not missing and smoke_test["passed"] and profile_matches,
            "target_collection": target_name,
            "database_backup": str(database_backup),
            "chroma_backup": str(chroma_backup) if chroma_backup else None,
        }
    finally:
        sqlite.release_vector_index_lock(owner)


def _migration_backups(database: Path, chroma_dir: Path) -> tuple[Path, Path | None]:
    """Create recoverable SQLite and Chroma snapshots before v4 writes."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    database = database.resolve()
    database_backup = database.with_name(
        f"{database.name}.migration-backup-{timestamp}"
    )
    with sqlite3.connect(database) as source, sqlite3.connect(database_backup) as backup:
        source.backup(backup)
    chroma_dir = chroma_dir.resolve()
    chroma_backup: Path | None = None
    if chroma_dir.exists():
        chroma_backup = chroma_dir.with_name(
            f"{chroma_dir.name}.migration-backup-{timestamp}"
        )
        shutil.copytree(chroma_dir, chroma_backup)
    return database_backup, chroma_backup


def _retrieval_smoke_test(target: Any, chunks: list[PaperChunk]) -> dict[str, Any]:
    """Verify one indexed chunk can be retrieved with its stored v4 vector."""
    if not chunks:
        return {"passed": True, "reason": "empty_source"}
    probe = chunks[0]
    entry = target.get_entry(probe.chunk_id, include_embedding=True)
    if not entry or not entry.get("embedding"):
        return {"passed": False, "reason": "probe_embedding_missing"}
    results = target.search(
        entry["embedding"],
        doc_ids=[probe.doc_id],
        top_k=min(5, len(chunks)),
    )
    return {
        "passed": probe.chunk_id in {chunk.chunk_id for chunk in results},
        "probe_chunk_id": probe.chunk_id,
    }


def verify(manager: VectorIndexManager) -> dict[str, Any]:
    result = manager.status()
    result["mode"] = "verify-only"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely migrate the CS Gap Assist vector index.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Apply or resume the migration.")
    mode.add_argument("--verify-only", action="store_true", help="Verify index state without migrating.")
    args = parser.parse_args()

    manager = VectorIndexManager(get_settings())
    if args.apply:
        result = asyncio.run(apply_migration(manager))
    elif args.verify_only:
        result = verify(manager)
    else:
        result = migration_plan(manager)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if not result.get("failed_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
