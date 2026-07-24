import argparse
import asyncio
import hashlib
import json
import os
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


def _source_vector(source_store, chunk: PaperChunk, dimension: int) -> list[float] | None:
    entry = source_store.get_entry(chunk.chunk_id, include_embedding=True)
    if not entry or entry.get("document") != chunk.text:
        return None
    vector = entry.get("embedding")
    if not isinstance(vector, list) or len(vector) != dimension:
        return None
    return [float(value) for value in vector]


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
    }


async def apply_migration(manager: VectorIndexManager) -> dict[str, Any]:
    """Apply or resume the deterministic migration without deleting legacy data."""
    sqlite = manager.sqlite
    profile = manager.profile
    source_name = LEGACY_COLLECTION
    target_name = profile.collection_name
    migration_id = _migration_id(profile.key, source_name, target_name)
    owner = f"{os.getpid()}:{migration_id}"
    if not sqlite.acquire_vector_index_lock(owner):
        raise RuntimeError("Another vector index migration is already in progress.")

    processed = 0
    skipped = 0
    failed = 0
    source = get_vector_store(manager.settings, collection_name=source_name)
    target = get_vector_store(manager.settings, profile=profile, collection_name=target_name)
    provider = configured_embedding_provider(manager.settings, document=True)
    sqlite.save_vector_migration(migration_id, profile.key, source_name, target_name, "running")
    sqlite.set_vector_index_state(profile.key, "migrating", manager.collection_name())
    try:
        for chunk in sqlite.list_chunks():
            if _target_is_current(target, chunk, profile.key):
                skipped += 1
                continue
            vector = _source_vector(source, chunk, profile.dimension)
            if vector is None:
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

        missing = [chunk.chunk_id for chunk in sqlite.list_chunks() if not _target_is_current(target, chunk, profile.key)]
        if failed or missing:
            sqlite.save_vector_migration(
                migration_id,
                profile.key,
                source_name,
                target_name,
                "failed",
                processed,
                skipped,
                max(failed, len(missing)),
                f"{len(missing)} chunks are not current in the target collection.",
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
            "failed_count": failed,
            "missing_count": len(missing),
            "activated": not failed and not missing,
            "target_collection": target_name,
        }
    finally:
        sqlite.release_vector_index_lock(owner)


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
