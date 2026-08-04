from __future__ import annotations

import argparse
import asyncio
import json
import math
import tempfile
import time
from pathlib import Path

from backend.core.config import Settings
from backend.models.schemas import PaperChunk
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.evidence_retriever import EvidenceRetriever


async def benchmark(chunk_count: int, runs: int) -> dict[str, float | int | bool]:
    """Measure the local 1k-chunk retrieval path without external network use."""
    with tempfile.TemporaryDirectory(prefix="cs-gap-benchmark-") as directory:
        root = Path(directory)
        settings = Settings(
            app_env="test",
            sqlite_url=str(root / "benchmark.db"),
            chroma_dir=str(root / "chroma"),
            document_dir=str(root / "documents"),
            external_network_enabled=False,
            default_embedding_provider="xfyun-spark",
            xfyun_spark_app_id=None,
            xfyun_spark_api_key=None,
            xfyun_spark_api_secret=None,
        )
        store = SQLiteStore(settings.sqlite_path)
        chunks = [
            PaperChunk(
                chunk_id=f"benchmark-{index:04d}",
                doc_id="benchmark-doc",
                page=(index // 4) + 1,
                ordinal=index,
                text=(
                    f"Chunk {index} discusses retrieval evaluation and robustness. "
                    + (
                        "Production drift causes measurable ranking degradation."
                        if index % 97 == 0
                        else "This is controlled benchmark filler evidence."
                    )
                ),
            )
            for index in range(chunk_count)
        ]
        store.add_paper("benchmark-doc", "Benchmark Paper", chunks)
        retriever = EvidenceRetriever(settings, store)
        latencies: list[float] = []
        duplicate_ratios: list[float] = []
        for _ in range(runs):
            started = time.perf_counter()
            result = await retriever.retrieve(
                "production drift ranking degradation",
                ["benchmark-doc"],
                top_k=8,
            )
            latencies.append((time.perf_counter() - started) * 1000)
            duplicate_ratios.append(result.duplicate_ratio)
        ordered = sorted(latencies)
        p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
        duplicate_ratio = sum(duplicate_ratios) / max(1, len(duplicate_ratios))
        return {
            "chunk_count": chunk_count,
            "runs": runs,
            "p95_ms": p95,
            "duplicate_ratio": duplicate_ratio,
            "passed": p95 < 1000.0 and duplicate_ratio < 0.15,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark local hybrid retrieval.")
    parser.add_argument("--chunks", type=int, default=1000)
    parser.add_argument("--runs", type=int, default=25)
    args = parser.parse_args()
    result = asyncio.run(benchmark(args.chunks, args.runs))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
