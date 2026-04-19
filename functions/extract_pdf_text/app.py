"""Multi-strategy PDF extraction Lambda.

Pipeline:
    1. Classify the PDF (page count, text coverage, scanned?, encrypted?)
    2. Pick a primary strategy based on the classification + env toggles
    3. Execute with automatic fallback down the chain on failure
    4. Persist concatenated Markdown as raw_text.txt (downstream Lambdas unchanged)
    5. Emit rich pdf_extraction metadata for observability / debugging

Strategies, in order of preference for text-native documents:
    A. text_layer  — PyMuPDF + pymupdf4llm → Markdown
    B. textract    — AWS Textract AnalyzeDocument per rendered page (OCR + tables + forms)
    C. vision      — OpenAI vision model transcribing rendered pages to Markdown
"""

from __future__ import annotations

import os
from typing import Any, Callable

from app_common.exceptions import DocumentExtractionError
from app_common.logging import get_logger, log_json
from app_common.s3_utils import get_object_bytes, put_text

from .classifier import Classification, classify
from .strategies import (
    PageContent,
    StrategyError,
    extract_text_layer,
    extract_via_textract,
    extract_via_vision,
)


logger = get_logger(__name__)


STRATEGY_TEXT_LAYER = "text_layer"
STRATEGY_TEXTRACT = "textract"
STRATEGY_VISION = "vision"

StrategyFn = Callable[[bytes], list[PageContent]]

STRATEGY_IMPLEMENTATIONS: dict[str, StrategyFn] = {
    STRATEGY_TEXT_LAYER: extract_text_layer,
    STRATEGY_TEXTRACT: extract_via_textract,
    STRATEGY_VISION: extract_via_vision,
}


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _choose_strategy_chain(classification: Classification) -> list[str]:
    enable_textract = _truthy(os.environ.get("ENABLE_TEXTRACT"), default=True)
    enable_vision = _truthy(os.environ.get("ENABLE_VISION_FALLBACK"), default=False)

    chain: list[str] = []

    if classification.is_encrypted:
        raise DocumentExtractionError("PDF is encrypted and no password was provided")
    if classification.is_corrupted:
        raise DocumentExtractionError("PDF is corrupted or has zero pages")

    if classification.is_scanned:
        if enable_textract:
            chain.append(STRATEGY_TEXTRACT)
        if enable_vision:
            chain.append(STRATEGY_VISION)
        if not chain:
            raise DocumentExtractionError(
                "PDF looks scanned but both Textract and vision fallback are disabled. "
                "Enable ENABLE_TEXTRACT or ENABLE_VISION_FALLBACK."
            )
        return chain

    chain.append(STRATEGY_TEXT_LAYER)
    if enable_textract:
        chain.append(STRATEGY_TEXTRACT)
    if enable_vision:
        chain.append(STRATEGY_VISION)
    return chain


def _run_with_fallback(
    pdf_bytes: bytes,
    chain: list[str],
    request_id: str,
) -> tuple[list[PageContent], str, list[dict[str, str]]]:
    attempts: list[dict[str, str]] = []
    last_error: Exception | None = None

    for strategy in chain:
        fn = STRATEGY_IMPLEMENTATIONS[strategy]
        try:
            pages = fn(pdf_bytes)
            attempts.append({"strategy": strategy, "outcome": "success"})
            return pages, strategy, attempts
        except StrategyError as exc:
            attempts.append({"strategy": strategy, "outcome": "failed", "reason": str(exc)})
            last_error = exc
            log_json(
                logger,
                "Strategy failed, falling back",
                request_id=request_id,
                strategy=strategy,
                error=str(exc),
            )
        except Exception as exc:
            attempts.append({"strategy": strategy, "outcome": "error", "reason": str(exc)})
            last_error = exc
            log_json(
                logger,
                "Strategy raised unexpected error",
                request_id=request_id,
                strategy=strategy,
                error=str(exc),
            )

    raise DocumentExtractionError(
        f"All strategies failed: {[a['strategy'] for a in attempts]}. "
        f"Last error: {last_error}"
    )


def _concat_pages(pages: list[PageContent]) -> str:
    return "\n\n".join(
        f"=== Page {p.page_number} ({p.method}) ===\n{p.markdown}"
        for p in pages
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    bucket = event["document"]["bucket"]
    key = event["document"]["key"]
    output_bucket = event["artifacts"]["output_bucket"]
    output_prefix = event["artifacts"]["output_prefix"]
    request_id = event["request_id"]

    pdf_bytes = get_object_bytes(bucket, key)

    classification = classify(pdf_bytes)
    log_json(
        logger,
        "PDF classified",
        request_id=request_id,
        **classification.to_dict(),
    )

    chain = _choose_strategy_chain(classification)
    pages, strategy_used, attempts = _run_with_fallback(pdf_bytes, chain, request_id)

    document_text = _concat_pages(pages)
    if not document_text.strip():
        raise DocumentExtractionError("Extraction produced empty text after all strategies")

    raw_text_key = f"{output_prefix}/raw_text.txt"
    put_text(output_bucket, raw_text_key, document_text)

    event["artifacts"]["raw_text"] = {
        "bucket": output_bucket,
        "key": raw_text_key,
    }
    event["pdf_extraction"] = {
        "engine": "multi_strategy",
        "strategy_used": strategy_used,
        "fallback_chain": chain,
        "attempts": attempts,
        "classification": classification.to_dict(),
        "pages": [p.to_dict() for p in pages],
        "total_char_count": sum(p.char_count for p in pages),
        "page_count": classification.page_count,
        "text_length": len(document_text),
    }

    log_json(
        logger,
        "PDF text extracted",
        request_id=request_id,
        strategy_used=strategy_used,
        page_count=classification.page_count,
        text_length=len(document_text),
    )
    return event
