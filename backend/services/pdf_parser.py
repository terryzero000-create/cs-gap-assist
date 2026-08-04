from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from backend.services.chunker import DocumentBlock, StructuredChunker


@dataclass(frozen=True)
class ParsedChunk:
    """Backward-compatible parsed chunk enriched with Chunker V2 metadata."""

    chunk_id: str
    page: int
    text: str
    page_end: int
    ordinal: int
    section_path: str
    char_start: int
    char_end: int
    block_type: str
    chunker_version: str
    content_hash: str
    injection_flagged: bool


@dataclass(frozen=True)
class PdfValidation:
    """Validated PDF properties used by the ingestion state machine."""

    page_count: int
    encrypted: bool
    needs_ocr: bool


@dataclass(frozen=True)
class OcrCapability:
    """Cached availability of the optional OCR runtime and language data."""

    available: bool
    detail: str


@lru_cache(maxsize=1)
def ocr_capability() -> OcrCapability:
    """Detect the optional Tesseract runtime once per process."""
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # noqa: F401
    except ImportError:
        return OcrCapability(False, "pytesseract or Pillow is not installed")
    try:
        pytesseract.get_tesseract_version()
        languages = set(pytesseract.get_languages(config=""))
    except Exception:
        return OcrCapability(False, "Tesseract executable is unavailable")
    missing = sorted({"chi_sim", "eng"} - languages)
    if missing:
        return OcrCapability(
            False,
            f"Tesseract language data is missing: {', '.join(missing)}",
        )
    return OcrCapability(True, "Tesseract with chi_sim and eng is available")


class PdfValidationError(ValueError):
    """Raised when bytes are not a safe, processable PDF."""

    def __init__(self, message: str, error_code: str, retryable: bool = False) -> None:
        self.error_code = error_code
        self.retryable = retryable
        super().__init__(message)


class PdfParser:
    """Layout-aware PDF parser with optional page-level OCR."""

    def __init__(
        self,
        *,
        max_pages: int = 500,
        max_payload_bytes: int = 6000,
        ocr_mode: Literal["disabled", "auto", "required"] = "auto",
        enable_ocr: bool | None = None,
    ) -> None:
        self.max_pages = max_pages
        self.chunker = StructuredChunker(max_payload_bytes=max_payload_bytes)
        if enable_ocr is not None:
            ocr_mode = "required" if enable_ocr else "disabled"
        self.ocr_mode = ocr_mode
        self.enable_ocr = ocr_mode != "disabled"
        self.warning_codes: list[str] = []
        self.warnings: list[str] = []

    def validate(self, content: bytes) -> PdfValidation:
        """Verify PDF signature, encryption, page count, and text availability."""
        if not content.startswith(b"%PDF-"):
            raise PdfValidationError("Uploaded file is not a real PDF.", "INVALID_PDF_FORMAT")
        try:
            import fitz  # type: ignore[import-not-found]

            document = fitz.open(stream=content, filetype="pdf")
        except Exception as exc:
            raise PdfValidationError(f"PDF is damaged or unreadable: {exc}", "DAMAGED_PDF") from exc
        try:
            if document.needs_pass:
                raise PdfValidationError("Encrypted PDFs are not supported.", "ENCRYPTED_PDF")
            if document.page_count < 1:
                raise PdfValidationError("PDF contains no pages.", "EMPTY_PDF")
            if document.page_count > self.max_pages:
                raise PdfValidationError(
                    f"PDF exceeds the {self.max_pages}-page limit.",
                    "PDF_PAGE_LIMIT",
                )
            low_text_pages = sum(
                1
                for page in document
                if len(re.findall(r"[\w\u3400-\u9fff]", page.get_text("text"))) < 40
            )
            needs_ocr = low_text_pages > 0
            return PdfValidation(
                page_count=document.page_count,
                encrypted=False,
                needs_ocr=needs_ocr,
            )
        finally:
            document.close()

    def parse(
        self,
        content: bytes,
        title: str,
        *,
        doc_id: str = "legacy",
        revision_id: str = "legacy",
        allow_text_fallback: bool = False,
    ) -> list[ParsedChunk]:
        """Extract layout blocks and return deterministic Chunker V2 chunks."""
        self.warning_codes = []
        self.warnings = []
        if not content.startswith(b"%PDF-") and allow_text_fallback:
            decoded = content.decode("utf-8", errors="ignore").strip()
            blocks = [DocumentBlock(page=1, text=decoded, section_path=title)] if decoded else []
        else:
            self.validate(content)
            blocks = self._extract_blocks(content)
        if not blocks:
            raise PdfValidationError(
                "PDF contains no extractable text; OCR is required.",
                "OCR_REQUIRED",
                retryable=True,
            )
        structured = self.chunker.chunk(blocks, doc_id=doc_id, revision_id=revision_id)
        if not structured:
            raise PdfValidationError("PDF produced no chunks.", "EMPTY_PDF_TEXT")
        return [
            ParsedChunk(
                chunk_id=item.chunk_id,
                page=item.page_start,
                page_end=item.page_end,
                ordinal=item.ordinal,
                text=item.text,
                section_path=item.section_path,
                char_start=item.char_start,
                char_end=item.char_end,
                block_type=item.block_type,
                chunker_version=item.chunker_version,
                content_hash=item.content_hash,
                injection_flagged=item.injection_flagged,
            )
            for item in structured
        ]

    def parse_file(
        self,
        path: Path,
        title: str,
        *,
        doc_id: str,
        revision_id: str,
    ) -> list[ParsedChunk]:
        """Parse one validated source file."""
        return self.parse(path.read_bytes(), title, doc_id=doc_id, revision_id=revision_id)

    def _extract_blocks(self, content: bytes) -> list[DocumentBlock]:
        import fitz  # type: ignore[import-not-found]

        document = fitz.open(stream=content, filetype="pdf")
        try:
            raw_pages: list[list[tuple[float, float, float, float, str, str]]] = []
            edge_lines: list[str] = []
            for page in document:
                page_blocks: list[tuple[float, float, float, float, str, str]] = []
                table_blocks: list[tuple[float, float, float, float, str, str]] = []
                try:
                    for table in page.find_tables().tables:
                        rows = table.extract()
                        markdown_rows = [
                            "| " + " | ".join((cell or "").strip() for cell in row) + " |"
                            for row in rows
                            if any((cell or "").strip() for cell in row)
                        ]
                        if markdown_rows:
                            x0, y0, x1, y1 = (float(value) for value in table.bbox)
                            table_blocks.append(
                                (x0, y0, x1, y1, "\n".join(markdown_rows), "table")
                            )
                except Exception:
                    table_blocks = []
                payload = page.get_text("dict", sort=False)
                height = float(page.rect.height or 1)
                for block in payload.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    lines = []
                    font_sizes: list[float] = []
                    font_names: list[str] = []
                    for line in block.get("lines", []):
                        line_text = "".join(str(span.get("text", "")) for span in line.get("spans", []))
                        if line_text.strip():
                            lines.append(line_text.strip())
                        for span in line.get("spans", []):
                            font_sizes.append(float(span.get("size", 0)))
                            font_names.append(str(span.get("font", "")))
                    text = "\n".join(lines).strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = (float(value) for value in block.get("bbox", (0, 0, 0, 0)))
                    if any(
                        x0 >= table[0] - 2
                        and y0 >= table[1] - 2
                        and x1 <= table[2] + 2
                        and y1 <= table[3] + 2
                        for table in table_blocks
                    ):
                        continue
                    block_type = self._block_type(text, font_sizes, font_names)
                    page_blocks.append((x0, y0, x1, y1, text, block_type))
                    if (
                        len(text) <= 300
                        and (y1 < height * 0.12 or y0 > height * 0.88)
                    ):
                        edge_lines.append(self._edge_key(text))
                page_blocks.extend(table_blocks)
                extracted_characters = len(
                    re.findall(r"[\w\u3400-\u9fff]", "\n".join(item[4] for item in page_blocks))
                )
                if extracted_characters < 40:
                    try:
                        page_blocks.extend(self._ocr_page(page))
                    except PdfValidationError as exc:
                        if self.ocr_mode == "required":
                            raise
                        self._add_warning(
                            "OCR_SKIPPED",
                            f"Skipped a low-text page because OCR is unavailable: {exc}",
                        )
                raw_pages.append(page_blocks)

            repeated_edges = {
                value
                for value, count in Counter(edge_lines).items()
                if value and count >= max(2, int(document.page_count * 0.6))
            }
            blocks: list[DocumentBlock] = []
            section = ""
            for page_number, page_blocks in enumerate(raw_pages, start=1):
                ordered = self._reading_order(page_blocks, float(document[page_number - 1].rect.width or 1))
                for _, _, _, _, text, block_type in ordered:
                    if self._edge_key(text) in repeated_edges:
                        continue
                    if block_type == "heading":
                        section = text[:500]
                    blocks.append(
                        DocumentBlock(
                            page=page_number,
                            text=text,
                            block_type=block_type,
                            section_path=section,
                        )
                    )
            return blocks
        finally:
            document.close()

    def _ocr_page(self, page: object) -> list[tuple[float, float, float, float, str, str]]:
        if not self.enable_ocr:
            return []
        capability = ocr_capability()
        if not capability.available:
            raise PdfValidationError(
                f"OCR is required but unavailable: {capability.detail}",
                "OCR_REQUIRED",
                retryable=True,
            )
        try:
            import fitz  # type: ignore[import-not-found]
            import pytesseract  # type: ignore[import-not-found]
            from PIL import Image

            pixmap = page.get_pixmap(matrix=fitz.Matrix(250 / 72, 250 / 72), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            text = pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
            if not text:
                return []
            rect = page.rect
            return [(0.0, 0.0, float(rect.width), float(rect.height), text, "ocr")]
        except Exception as exc:
            raise PdfValidationError(
                f"OCR is required but unavailable: {exc}",
                "OCR_REQUIRED",
                retryable=True,
            ) from exc

    def _add_warning(self, code: str, warning: str) -> None:
        """Record one parser warning without duplicating it for every page."""
        if code in self.warning_codes:
            return
        self.warning_codes.append(code)
        self.warnings.append(warning)

    @staticmethod
    def _reading_order(
        blocks: list[tuple[float, float, float, float, str, str]],
        page_width: float,
    ) -> list[tuple[float, float, float, float, str, str]]:
        left = [item for item in blocks if item[2] <= page_width * 0.62]
        right = [item for item in blocks if item[0] >= page_width * 0.38]
        spanning = [item for item in blocks if item not in left and item not in right]
        if len(left) >= 2 and len(right) >= 2:
            ordered: list[tuple[float, float, float, float, str, str]] = []
            previous_y = float("-inf")
            for span in sorted(spanning, key=lambda item: (item[1], item[0])):
                band_left = [
                    item for item in left if previous_y <= item[1] < span[1]
                ]
                band_right = [
                    item for item in right if previous_y <= item[1] < span[1]
                ]
                ordered.extend(sorted(band_left, key=lambda item: (item[1], item[0])))
                ordered.extend(sorted(band_right, key=lambda item: (item[1], item[0])))
                ordered.append(span)
                previous_y = span[1]
            ordered.extend(
                sorted(
                    [item for item in left if item[1] >= previous_y],
                    key=lambda item: (item[1], item[0]),
                )
            )
            ordered.extend(
                sorted(
                    [item for item in right if item[1] >= previous_y],
                    key=lambda item: (item[1], item[0]),
                )
            )
            return ordered
        return sorted(blocks, key=lambda item: (item[1], item[0]))

    @staticmethod
    def _block_type(text: str, sizes: list[float], fonts: list[str]) -> str:
        lines = text.splitlines()
        average_size = sum(sizes) / len(sizes) if sizes else 0
        if len(text) <= 180 and (average_size >= 14 or re.match(r"^\d+(?:\.\d+)*\s+\S+", text)):
            return "heading"
        if len(lines) >= 3 and sum(bool(re.match(r"^\s{2,}|\t|(?:def|class|import|from)\s", line)) for line in lines) >= 2:
            return "code"
        if any(symbol in text for symbol in ("∑", "∫", "√", "≤", "≥", "→", "λ", "θ")):
            return "formula"
        if any("mono" in font.casefold() or "courier" in font.casefold() for font in fonts):
            return "code"
        if len(lines) >= 2 and all(len(re.split(r"\s{2,}|\t", line)) >= 2 for line in lines[:3]):
            return "table"
        return "text"

    @staticmethod
    def _edge_key(text: str) -> str:
        return re.sub(r"\d+", "#", " ".join(text.casefold().split()))[:200]
