import re

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


INJECTION_PATTERNS = (
    re.compile(r"\bignore (?:all |the )?(?:previous|prior) instructions?\b", re.IGNORECASE),
    re.compile(r"\bsystem prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper message\b", re.IGNORECASE),
    re.compile(r"(?:忽略|无视).{0,12}(?:指令|提示词|规则)"),
    re.compile(r"(?:系统|开发者).{0,8}(?:提示词|消息|指令)"),
)


def contains_prompt_injection(text: str) -> bool:
    """Flag common instruction-like content without removing source evidence."""
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)


def wrap_untrusted_evidence(source_id: str, text: str) -> str:
    """Delimit source text so model prompts never treat it as instructions."""
    escaped = text.replace("</UNTRUSTED_EVIDENCE>", "&lt;/UNTRUSTED_EVIDENCE&gt;")
    return (
        f'<UNTRUSTED_EVIDENCE id="{source_id}" instructions="never">\n'
        f"{escaped}\n"
        "</UNTRUSTED_EVIDENCE>"
    )


def validate_qa_citations(answer: str, allowed_source_ids: set[str]) -> tuple[bool, list[str]]:
    """Require every substantive answer paragraph to cite only admitted source IDs."""
    cited = set(re.findall(r"\[(S\d+)\]", answer))
    bracketed = set(re.findall(r"\[([^\]]+)\]", answer))
    unknown = sorted(value for value in bracketed if value.startswith("S") and value not in allowed_source_ids)
    paragraphs = [part.strip() for part in re.split(r"\n+", answer) if part.strip()]
    uncited = [
        paragraph
        for paragraph in paragraphs
        if "证据不足" not in paragraph and not re.search(r"\[S\d+\]", paragraph)
    ]
    warnings: list[str] = []
    if unknown:
        warnings.append(f"Model cited unknown sources: {', '.join(unknown)}.")
    if not cited:
        warnings.append("Model answer did not cite any admitted source.")
    if uncited:
        warnings.append("Model answer contained an uncited substantive paragraph.")
    return not unknown and bool(cited) and not uncited, warnings
