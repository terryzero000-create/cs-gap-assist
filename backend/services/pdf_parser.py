from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class ParsedChunk:
    """A page-aware chunk extracted from a PDF or text fallback."""

    chunk_id: str
    page: int
    text: str


class PdfParser:
    """Parse PDF bytes into page-aware chunks with a text fallback."""

    def parse(self, content: bytes, title: str) -> list[ParsedChunk]:
        """Extract chunks from a PDF byte stream."""
        text_by_page = self._extract_pages(content)
        chunks: list[ParsedChunk] = []
        for page, text in enumerate(text_by_page, start=1):
            chunks.extend(self._chunk_page(text, page))
        if not chunks:
            chunks.append(ParsedChunk(chunk_id=str(uuid4()), page=1, text=f"Uploaded paper {title}"))
        return chunks

    def _extract_pages(self, content: bytes) -> list[str]:
        """Try PyMuPDF first and fall back to UTF-8 text decoding."""
        try:
            import fitz  # type: ignore[import-not-found]

            document = fitz.open(stream=content, filetype="pdf")
            return [page.get_text().strip() for page in document if page.get_text().strip()]
        except Exception:
            decoded = content.decode("utf-8", errors="ignore").strip()
            return [decoded] if decoded else []

    def _chunk_page(self, text: str, page: int, max_chars: int = 900) -> list[ParsedChunk]:
        """Split a page into compact chunks for retrieval."""
        normalized = " ".join(text.split())
        if not normalized:
            return []
        return [
            ParsedChunk(chunk_id=str(uuid4()), page=page, text=normalized[index : index + max_chars])
            for index in range(0, len(normalized), max_chars)
        ]
