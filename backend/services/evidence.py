from backend.models.schemas import EvidenceRef, EvidenceStatus
from backend.services.external_paper import ExternalPaper


def external_paper_ref(paper: ExternalPaper) -> EvidenceRef:
    """Convert an externally returned paper into a canonical trusted reference."""
    if paper.paper_id.startswith("arxiv-"):
        arxiv_id = paper.paper_id.removeprefix("arxiv-")
        return EvidenceRef(
            source="arxiv",
            id=paper.paper_id,
            title=paper.title,
            canonical_url=paper.canonical_url or f"https://arxiv.org/abs/{arxiv_id}",
        )
    return EvidenceRef(
        source="openalex",
        id=paper.paper_id,
        title=paper.title,
        canonical_url=paper.canonical_url or f"https://openalex.org/works/{paper.paper_id}",
    )


def match_evidence_refs(values: object, allowed_refs: list[EvidenceRef]) -> list[EvidenceRef]:
    """Resolve model-produced identifiers only against the current trusted evidence pool."""
    if not isinstance(values, list):
        return []
    aliases: dict[str, EvidenceRef] = {}
    for ref in allowed_refs:
        for value in (ref.id, ref.title, ref.canonical_url, f"{ref.id}: {ref.title}"):
            aliases[_normalize(value)] = ref
    matched: list[EvidenceRef] = []
    seen: set[str] = set()
    for value in values:
        ref = aliases.get(_normalize(str(value)))
        if ref and ref.id not in seen:
            matched.append(ref)
            seen.add(ref.id)
    return matched


def evidence_status(refs: list[EvidenceRef]) -> EvidenceStatus:
    """Return the strongest truthful status represented by a reference set."""
    if any(ref.source in {"arxiv", "openalex"} for ref in refs):
        return "verified"
    if any(ref.source == "local" for ref in refs):
        return "local_only"
    return "insufficient_evidence"


def _normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())
