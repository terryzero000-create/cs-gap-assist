from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.config import Settings, get_settings
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.evidence_retriever import EvidenceRetriever


MINIMUM_CASES = 36


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    doc_ids: list[str]
    answerable: bool
    relevant_chunk_ids: set[str]


def _load_cases(path: Path, allow_small_dataset: bool) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        EvalCase(
            id=str(item["id"]),
            question=str(item["question"]),
            doc_ids=[str(value) for value in item["doc_ids"]],
            answerable=bool(item["answerable"]),
            relevant_chunk_ids={str(value) for value in item["relevant_chunk_ids"]},
        )
        for item in payload.get("cases", [])
    ]
    if not allow_small_dataset and len(cases) < MINIMUM_CASES:
        raise ValueError(
            f"Release evaluation requires at least {MINIMUM_CASES} manually reviewed cases; "
            f"found {len(cases)}."
        )
    if any(case.answerable and not case.relevant_chunk_ids for case in cases):
        raise ValueError("Every answerable case requires at least one relevant chunk ID.")
    return cases


def ranking_metrics(
    predictions: list[list[str]],
    cases: list[EvalCase],
) -> dict[str, float]:
    """Compute deterministic retrieval gates from stable chunk IDs."""
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    no_answer: list[float] = []
    duplicate_ratios: list[float] = []
    for predicted, case in zip(predictions, cases, strict=True):
        duplicate_ratios.append(
            1.0 - len(set(predicted)) / max(1, len(predicted))
        )
        if not case.answerable:
            no_answer.append(float(not predicted))
            continue
        top5 = predicted[:5]
        recalls.append(
            len(set(top5) & case.relevant_chunk_ids)
            / max(1, len(case.relevant_chunk_ids))
        )
        first_rank = next(
            (
                index
                for index, chunk_id in enumerate(predicted[:10], start=1)
                if chunk_id in case.relevant_chunk_ids
            ),
            None,
        )
        reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
        dcg = sum(
            1.0 / math.log2(index + 1)
            for index, chunk_id in enumerate(predicted[:10], start=1)
            if chunk_id in case.relevant_chunk_ids
        )
        ideal_hits = min(len(case.relevant_chunk_ids), 10)
        ideal = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
        ndcgs.append(dcg / ideal if ideal else 0.0)
    return {
        "recall_at_5": statistics.fmean(recalls) if recalls else 0.0,
        "mrr_at_10": statistics.fmean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "ndcg_at_10": statistics.fmean(ndcgs) if ndcgs else 0.0,
        "no_answer_accuracy": statistics.fmean(no_answer) if no_answer else 0.0,
        "top_k_duplicate_ratio": (
            statistics.fmean(duplicate_ratios) if duplicate_ratios else 0.0
        ),
    }


def citation_metrics(
    claim_citations: list[list[str]],
    valid_evidence_ids: set[str],
) -> dict[str, float]:
    """Measure citation precision and claim-level citation coverage."""
    cited = [
        citation
        for citations in claim_citations
        for citation in citations
    ]
    valid_count = sum(
        citation in valid_evidence_ids
        for citation in cited
    )
    covered_claims = sum(
        bool(set(citations) & valid_evidence_ids)
        for citations in claim_citations
    )
    return {
        "citation_precision": valid_count / max(1, len(cited)),
        "claim_citation_coverage": covered_claims
        / max(1, len(claim_citations)),
    }


async def _evaluate_profile(
    base: Settings,
    cases: list[EvalCase],
    profile: dict[str, float | int],
) -> dict[str, Any]:
    settings = base.model_copy(
        update={
            "rag_vector_weight": profile["vector_weight"],
            "rag_lexical_weight": profile["lexical_weight"],
            "rag_rrf_k": profile["rrf_k"],
            "rag_mmr_lambda": profile["mmr_lambda"],
            "rag_min_semantic_score": profile["semantic_threshold"],
            "rag_min_lexical_score": profile["lexical_threshold"],
            "rag_final_top_k": 10,
        }
    )
    store = SQLiteStore(settings.sqlite_path)
    predictions: list[list[str]] = []
    latencies: list[float] = []
    duplicate_ratios: list[float] = []
    for case in cases:
        result = await EvidenceRetriever(settings, store).retrieve(
            case.question,
            case.doc_ids,
            top_k=10,
        )
        predictions.append([chunk.chunk_id for chunk in result.chunks])
        latencies.append(result.latency_ms)
        duplicate_ratios.append(result.duplicate_ratio)
    metrics = ranking_metrics(predictions, cases)
    metrics["retrieval_p95_ms"] = (
        sorted(latencies)[max(0, math.ceil(0.95 * len(latencies)) - 1)]
        if latencies
        else 0.0
    )
    metrics["top_k_duplicate_ratio"] = (
        statistics.fmean(duplicate_ratios) if duplicate_ratios else 0.0
    )
    return {"profile": profile, "metrics": metrics}


def _grid() -> list[dict[str, float | int]]:
    profiles: list[dict[str, float | int]] = []
    for vector_weight, rrf_k, mmr_lambda, semantic, lexical in itertools.product(
        (0.45, 0.55, 0.65),
        (40, 60, 80),
        (0.6, 0.7, 0.8),
        (0.25, 0.35, 0.45),
        (0.03, 0.05, 0.1),
    ):
        profiles.append(
            {
                "vector_weight": vector_weight,
                "lexical_weight": round(1.0 - vector_weight, 2),
                "rrf_k": rrf_k,
                "mmr_lambda": mmr_lambda,
                "semantic_threshold": semantic,
                "lexical_threshold": lexical,
            }
        )
    return profiles


async def grid_search(
    settings: Settings,
    cases: list[EvalCase],
) -> dict[str, Any]:
    """Select highest nDCG among profiles satisfying hard recall/no-answer gates."""
    results = [
        await _evaluate_profile(settings, cases, profile)
        for profile in _grid()
    ]
    eligible = [
        result
        for result in results
        if result["metrics"]["recall_at_5"] >= 0.85
        and result["metrics"]["no_answer_accuracy"] >= 0.90
    ]
    best = max(
        eligible,
        key=lambda result: (
            result["metrics"]["ndcg_at_10"],
            result["metrics"]["mrr_at_10"],
            -result["metrics"]["top_k_duplicate_ratio"],
        ),
        default=None,
    )
    return {
        "case_count": len(cases),
        "evaluated_profile_count": len(results),
        "eligible_profile_count": len(eligible),
        "best": best,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline CS Gap Assist RAG grid search.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("backend/evals/rag_profile.json"))
    parser.add_argument("--allow-small-dataset", action="store_true")
    args = parser.parse_args()
    cases = _load_cases(args.dataset, args.allow_small_dataset)
    result = asyncio.run(grid_search(get_settings(), cases))
    if not result["best"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    current = json.loads(args.output.read_text(encoding="utf-8"))
    current["status"] = "evaluated"
    current["retrieval"].update(result["best"]["profile"])
    current["last_evaluation"] = result
    args.output.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
