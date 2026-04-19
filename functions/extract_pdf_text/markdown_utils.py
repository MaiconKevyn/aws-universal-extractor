"""Convert raw PDF content (PyMuPDF or Textract) into Markdown.

LLMs extract 2-3x more reliably from Markdown than from raw text — tables keep
their structure, headings survive, and reading order is preserved.
"""

from __future__ import annotations

from typing import Any

import fitz

try:
    import pymupdf4llm
    HAS_PYMUPDF4LLM = True
except ImportError:
    HAS_PYMUPDF4LLM = False


def pymupdf_doc_to_markdown_pages(doc: fitz.Document) -> list[str]:
    """Return one Markdown string per page, preserving layout and tables."""
    if HAS_PYMUPDF4LLM:
        try:
            pages = pymupdf4llm.to_markdown(
                doc,
                page_chunks=True,
                write_images=False,
                show_progress=False,
            )
            return [chunk.get("text", "").strip() for chunk in pages]
        except Exception:
            pass

    return [_page_to_markdown_fallback(page) for page in doc]


def _page_to_markdown_fallback(page: fitz.Page) -> str:
    blocks = page.get_text("blocks") or []
    blocks.sort(key=lambda b: (round(b[1], 1), round(b[0], 1)))
    lines: list[str] = []
    for block in blocks:
        text = (block[4] or "").strip()
        if text:
            lines.append(text)
    return "\n\n".join(lines)


def textract_blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Convert a Textract AnalyzeDocument / DetectDocumentText response blocks list
    into a Markdown document. LINE blocks become paragraphs, TABLE blocks become
    Markdown tables using CELL blocks arranged by RowIndex / ColumnIndex.
    """
    if not blocks:
        return ""

    by_id = {b["Id"]: b for b in blocks if "Id" in b}
    page_blocks = [b for b in blocks if b.get("BlockType") == "PAGE"]

    rendered: list[str] = []
    for page_block in page_blocks or [None]:
        page_children = _child_ids(page_block) if page_block else None
        if page_children is None:
            scope = blocks
        else:
            scope = [by_id[cid] for cid in page_children if cid in by_id]

        tables = [b for b in scope if b.get("BlockType") == "TABLE"]
        lines = [b for b in scope if b.get("BlockType") == "LINE"]

        table_word_ids: set[str] = set()
        for t in tables:
            for cid in _child_ids(t):
                cell = by_id.get(cid)
                if cell and cell.get("BlockType") == "CELL":
                    for wid in _child_ids(cell):
                        table_word_ids.add(wid)

        paragraph_lines = [
            l for l in lines
            if not (set(_child_ids(l)) & table_word_ids)
        ]
        paragraph_lines.sort(key=_reading_order_key)
        if paragraph_lines:
            rendered.append("\n".join(l.get("Text", "") for l in paragraph_lines))

        for table in tables:
            md = _textract_table_to_markdown(table, by_id)
            if md:
                rendered.append(md)

    return "\n\n".join(r for r in rendered if r.strip())


def _textract_table_to_markdown(table: dict[str, Any], by_id: dict[str, dict]) -> str:
    cells: list[dict] = []
    for cid in _child_ids(table):
        block = by_id.get(cid)
        if block and block.get("BlockType") == "CELL":
            cells.append(block)

    if not cells:
        return ""

    rows: dict[int, dict[int, str]] = {}
    max_col = 0
    for cell in cells:
        row = cell.get("RowIndex", 0)
        col = cell.get("ColumnIndex", 0)
        max_col = max(max_col, col)
        text_parts: list[str] = []
        for wid in _child_ids(cell):
            word = by_id.get(wid)
            if word and word.get("BlockType") in ("WORD", "SELECTION_ELEMENT"):
                if word.get("BlockType") == "SELECTION_ELEMENT":
                    text_parts.append("[X]" if word.get("SelectionStatus") == "SELECTED" else "[ ]")
                else:
                    text_parts.append(word.get("Text", ""))
        rows.setdefault(row, {})[col] = " ".join(text_parts).strip()

    if not rows:
        return ""

    sorted_rows = sorted(rows.keys())
    md_rows: list[str] = []
    for i, r in enumerate(sorted_rows):
        cells_text = [rows[r].get(c, "") for c in range(1, max_col + 1)]
        md_rows.append("| " + " | ".join(cells_text) + " |")
        if i == 0:
            md_rows.append("| " + " | ".join(["---"] * max_col) + " |")
    return "\n".join(md_rows)


def _child_ids(block: dict[str, Any]) -> list[str]:
    for rel in block.get("Relationships", []) or []:
        if rel.get("Type") == "CHILD":
            return rel.get("Ids", [])
    return []


def _reading_order_key(block: dict[str, Any]) -> tuple[float, float]:
    bbox = block.get("Geometry", {}).get("BoundingBox", {})
    return (round(bbox.get("Top", 0.0), 2), round(bbox.get("Left", 0.0), 2))
