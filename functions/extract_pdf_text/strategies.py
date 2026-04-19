"""Extraction strategies. Each takes PDF bytes and returns a list of PageContent.

Strategies are pure (no S3 I/O, no event mutation). The orchestrator in app.py
picks which strategy to run based on the Classification and configurable toggles.
"""

from __future__ import annotations

import base64
import io
import os
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

import boto3
import fitz

from app_common.config import get_settings, load_secret

from .markdown_utils import (
    pymupdf_doc_to_markdown_pages,
    textract_blocks_to_markdown,
)


TEXTRACT_FEATURES = ("TABLES", "FORMS")
DEFAULT_RENDER_DPI = 220


@dataclass
class PageContent:
    page_number: int
    markdown: str
    method: str
    char_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StrategyError(RuntimeError):
    pass


def extract_text_layer(pdf_bytes: bytes) -> list[PageContent]:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page_markdowns = pymupdf_doc_to_markdown_pages(doc)

    pages: list[PageContent] = []
    for index, md in enumerate(page_markdowns, start=1):
        md = md.strip()
        if not md:
            continue
        pages.append(PageContent(
            page_number=index,
            markdown=md,
            method="pymupdf_text_markdown",
            char_count=len(md),
        ))

    if not pages:
        raise StrategyError("text_layer extraction produced no content")
    return pages


def extract_via_textract(
    pdf_bytes: bytes,
    *,
    textract_client: Optional[Any] = None,
    render_dpi: int = DEFAULT_RENDER_DPI,
) -> list[PageContent]:
    """Render each page to PNG and call sync Textract AnalyzeDocument.

    Page-by-page sync (instead of async StartDocumentAnalysis) gives predictable
    latency, works for any page count, and keeps the Lambda stateless. For very
    long documents (>20 pages) async with SNS notification is the correct pattern;
    left as a follow-up.

    Textract is not available in every region (e.g. sa-east-1 has no endpoint).
    Set TEXTRACT_REGION to call a region that has the service while the rest of
    the pipeline stays where the data lives.
    """
    if textract_client is None:
        region = os.environ.get("TEXTRACT_REGION") or os.environ.get("AWS_REGION")
        textract_client = boto3.client("textract", region_name=region)
    client = textract_client
    pages: list[PageContent] = []

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for index, page in enumerate(doc, start=1):
            png_bytes = _render_page_png(page, dpi=render_dpi)
            try:
                response = client.analyze_document(
                    Document={"Bytes": png_bytes},
                    FeatureTypes=list(TEXTRACT_FEATURES),
                )
            except Exception as exc:
                raise StrategyError(f"Textract failed on page {index}: {exc}") from exc

            blocks = response.get("Blocks", [])
            md = textract_blocks_to_markdown(blocks).strip()
            if not md:
                continue
            pages.append(PageContent(
                page_number=index,
                markdown=md,
                method="aws_textract_analyze",
                char_count=len(md),
            ))

    if not pages:
        raise StrategyError("textract extraction produced no content")
    return pages


def extract_via_vision(
    pdf_bytes: bytes,
    *,
    openai_client_factory: Optional[Callable[[], Any]] = None,
    model: Optional[str] = None,
    render_dpi: int = DEFAULT_RENDER_DPI,
) -> list[PageContent]:
    """Render each page to PNG and ask a vision model to transcribe to Markdown."""
    from openai import OpenAI

    if openai_client_factory:
        client = openai_client_factory()
    else:
        client = OpenAI(**_openai_client_kwargs())
    model = model or os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")

    pages: list[PageContent] = []

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for index, page in enumerate(doc, start=1):
            png_bytes = _render_page_png(page, dpi=render_dpi)
            b64 = base64.b64encode(png_bytes).decode("ascii")
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Transcribe this document page into Markdown. "
                                    "Preserve tables as Markdown tables. Preserve "
                                    "headings and reading order. Return only the "
                                    "Markdown, no preamble."
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            },
                        ],
                    }],
                    temperature=0,
                )
            except Exception as exc:
                raise StrategyError(f"vision extraction failed on page {index}: {exc}") from exc

            md = (response.choices[0].message.content or "").strip()
            if not md:
                continue
            pages.append(PageContent(
                page_number=index,
                markdown=md,
                method=f"openai_vision_{model}",
                char_count=len(md),
            ))

    if not pages:
        raise StrategyError("vision extraction produced no content")
    return pages


def _render_page_png(page: fitz.Page, *, dpi: int) -> bytes:
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    buf = io.BytesIO(pixmap.tobytes("png"))
    return buf.getvalue()


def _openai_client_kwargs() -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key and settings.openai_api_key_secret_arn:
        api_key = load_secret(settings.openai_api_key_secret_arn)

    if not api_key:
        raise StrategyError("OPENAI_API_KEY or OPENAI_API_KEY_SECRET_ARN must be configured for vision fallback")

    kwargs: dict[str, Any] = {"api_key": api_key}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return kwargs
