"""PDF triage: classify a document before choosing an extraction strategy.

Pure, no I/O. Takes PDF bytes, returns a Classification that downstream code
uses to pick between text-layer, OCR, or vision strategies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import fitz


SCANNED_CHARS_PER_PAGE = 50
SPARSE_CHARS_PER_PAGE = 200
TABLE_LINE_MIN_CELLS = 3


@dataclass(frozen=True)
class Classification:
    page_count: int
    is_encrypted: bool
    is_corrupted: bool
    is_scanned: bool
    is_sparse: bool
    has_tables: bool
    avg_chars_per_page: float
    text_coverage: float
    total_char_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify(pdf_bytes: bytes) -> Classification:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return Classification(
            page_count=0,
            is_encrypted=False,
            is_corrupted=True,
            is_scanned=False,
            is_sparse=True,
            has_tables=False,
            avg_chars_per_page=0.0,
            text_coverage=0.0,
            total_char_count=0,
        )

    with doc:
        if doc.is_encrypted and not doc.authenticate(""):
            return Classification(
                page_count=doc.page_count,
                is_encrypted=True,
                is_corrupted=False,
                is_scanned=False,
                is_sparse=True,
                has_tables=False,
                avg_chars_per_page=0.0,
                text_coverage=0.0,
                total_char_count=0,
            )

        page_count = doc.page_count
        if page_count == 0:
            return Classification(
                page_count=0,
                is_encrypted=False,
                is_corrupted=True,
                is_scanned=False,
                is_sparse=True,
                has_tables=False,
                avg_chars_per_page=0.0,
                text_coverage=0.0,
                total_char_count=0,
            )

        total_chars = 0
        total_area = 0.0
        table_hits = 0

        for page in doc:
            text = page.get_text("text") or ""
            total_chars += len(text)
            total_area += page.rect.width * page.rect.height

            if _looks_tabular(text):
                table_hits += 1

        avg_chars = total_chars / page_count if page_count else 0.0
        coverage = total_chars / total_area if total_area > 0 else 0.0

        is_scanned = avg_chars < SCANNED_CHARS_PER_PAGE
        is_sparse = avg_chars < SPARSE_CHARS_PER_PAGE and not is_scanned
        has_tables = table_hits >= max(1, page_count // 3)

        return Classification(
            page_count=page_count,
            is_encrypted=False,
            is_corrupted=False,
            is_scanned=is_scanned,
            is_sparse=is_sparse,
            has_tables=has_tables,
            avg_chars_per_page=round(avg_chars, 2),
            text_coverage=round(coverage, 4),
            total_char_count=total_chars,
        )


def _looks_tabular(text: str) -> bool:
    if not text:
        return False
    aligned_lines = 0
    for line in text.splitlines():
        tokens = [t for t in line.split() if t]
        if len(tokens) >= TABLE_LINE_MIN_CELLS and (
            "  " in line or "\t" in line or any(ch in line for ch in "|")
        ):
            aligned_lines += 1
    return aligned_lines >= 3
