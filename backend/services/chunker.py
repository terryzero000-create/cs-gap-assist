import base64
import hashlib
import json
import re
from dataclasses import dataclass

from backend.services.evidence import contains_prompt_injection


CHUNKER_VERSION = "chunker-v2"
DEFAULT_OVERLAP_RATIO = 0.12


def xfyun_request_payload_bytes(
    text: str,
    *,
    app_id: str = "",
    domain: str = "para",
) -> int:
    """Return exact UTF-8 bytes of the final JSON/base64 embedding body."""
    text_object = {"messages": [{"content": text, "role": "user"}]}
    encoded = base64.b64encode(
        json.dumps(
            text_object,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode()
    body = {
        "header": {"app_id": app_id, "uid": "39769795890", "status": 3},
        "parameter": {
            "emb": {
                "domain": domain,
                "feature": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "plain",
                },
            }
        },
        "payload": {
            "messages": {
                "encoding": "utf8",
                "compress": "raw",
                "format": "json",
                "status": 3,
                "text": encoded,
            }
        },
    }
    return len(
        json.dumps(
            body,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


@dataclass(frozen=True)
class DocumentBlock:
    """One ordered, typed unit extracted from a document page."""

    page: int
    text: str
    block_type: str = "text"
    section_path: str = ""


@dataclass(frozen=True)
class StructuredChunk:
    """Stable chunk with enough metadata for retrieval and reconstruction."""

    chunk_id: str
    ordinal: int
    page_start: int
    page_end: int
    text: str
    section_path: str
    char_start: int
    char_end: int
    block_type: str
    chunker_version: str
    content_hash: str
    injection_flagged: bool


class StructuredChunker:
    """Recursively split blocks while respecting the serialized provider payload."""

    def __init__(
        self,
        max_payload_bytes: int = 6000,
        overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
        short_tail_ratio: float = 0.2,
    ) -> None:
        self.max_payload_bytes = max_payload_bytes
        self.overlap_ratio = overlap_ratio
        self.short_tail_ratio = short_tail_ratio

    def chunk(
        self,
        blocks: list[DocumentBlock],
        *,
        doc_id: str,
        revision_id: str,
    ) -> list[StructuredChunk]:
        """Return deterministic chunks in document order."""
        candidates: list[tuple[DocumentBlock, str]] = []
        for block in blocks:
            normalized = self._normalize(block.text)
            if not normalized:
                continue
            for piece in self._split_to_payload(normalized):
                candidates.append((block, piece))
        candidates = self._merge_short_tails(candidates)

        chunks: list[StructuredChunk] = []
        char_cursor = 0
        previous_text = ""
        for ordinal, (block, text) in enumerate(candidates):
            overlap = self._overlap_text(previous_text)
            combined = f"{overlap} {text}".strip() if overlap else text
            if not self._fits_payload(combined):
                combined = text
            content_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
            chunk_key = f"{doc_id}\n{revision_id}\n{ordinal}\n{content_hash}".encode("utf-8")
            chunk_id = hashlib.sha256(chunk_key).hexdigest()
            char_start = max(0, char_cursor - len(overlap))
            char_end = char_start + len(combined)
            chunks.append(
                StructuredChunk(
                    chunk_id=chunk_id,
                    ordinal=ordinal,
                    page_start=block.page,
                    page_end=block.page,
                    text=combined,
                    section_path=block.section_path,
                    char_start=char_start,
                    char_end=char_end,
                    block_type=block.block_type,
                    chunker_version=CHUNKER_VERSION,
                    content_hash=content_hash,
                    injection_flagged=contains_prompt_injection(combined),
                )
            )
            char_cursor += len(text) + 1
            previous_text = text
        return chunks

    def _split_to_payload(self, text: str) -> list[str]:
        if self._fits_payload(text):
            return [text]
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
        if len(paragraphs) > 1:
            return self._pack_units(paragraphs)
        sentences = [
            part.strip()
            for part in re.split(r"(?<=[。！？.!?])\s+|(?<=[。！？])", text)
            if part.strip()
        ]
        if len(sentences) > 1:
            return self._pack_units(sentences)
        return self._split_by_codepoint(text)

    def _pack_units(self, units: list[str]) -> list[str]:
        pieces: list[str] = []
        current = ""
        for unit in units:
            candidate = f"{current} {unit}".strip()
            if current and not self._fits_payload(candidate):
                pieces.extend(self._split_to_payload(current) if not self._fits_payload(current) else [current])
                current = unit
            else:
                current = candidate
        if current:
            pieces.extend(self._split_to_payload(current) if not self._fits_payload(current) else [current])
        return pieces

    def _split_by_codepoint(self, text: str) -> list[str]:
        pieces: list[str] = []
        start = 0
        while start < len(text):
            low, high = start + 1, len(text)
            best = low
            while low <= high:
                middle = (low + high) // 2
                if self._fits_payload(text[start:middle]):
                    best = middle
                    low = middle + 1
                else:
                    high = middle - 1
            pieces.append(text[start:best].strip())
            start = best
        return [piece for piece in pieces if piece]

    def _merge_short_tails(
        self,
        candidates: list[tuple[DocumentBlock, str]],
    ) -> list[tuple[DocumentBlock, str]]:
        if len(candidates) < 2:
            return candidates
        merged = list(candidates)
        previous_block, previous_text = merged[-2]
        tail_block, tail_text = merged[-1]
        if (
            self._payload_bytes(tail_text) < self.max_payload_bytes * self.short_tail_ratio
            and previous_block.page == tail_block.page
            and previous_block.section_path == tail_block.section_path
            and previous_block.block_type == tail_block.block_type
            and self._fits_payload(f"{previous_text} {tail_text}")
        ):
            merged[-2] = (
                DocumentBlock(
                    page=previous_block.page,
                    text=previous_block.text,
                    block_type=previous_block.block_type,
                    section_path=previous_block.section_path,
                ),
                f"{previous_text} {tail_text}".strip(),
            )
            merged.pop()
        return merged

    def _overlap_text(self, previous: str) -> str:
        if not previous:
            return ""
        target = max(0, int(len(previous) * self.overlap_ratio))
        if target == 0:
            return ""
        start = max(0, len(previous) - target)
        boundary = previous.find(" ", start)
        return previous[boundary + 1 :] if boundary >= 0 else previous[start:]

    def _fits_payload(self, text: str) -> bool:
        return self._payload_bytes(text) <= self.max_payload_bytes

    @staticmethod
    def _payload_bytes(text: str) -> int:
        return xfyun_request_payload_bytes(text)

    @staticmethod
    def _normalize(text: str) -> str:
        lines = [" ".join(line.split()) for line in text.splitlines()]
        return "\n".join(line for line in lines if line).strip()
