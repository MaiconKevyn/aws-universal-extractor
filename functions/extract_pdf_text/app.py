from typing import Any

import fitz

from app_common.exceptions import DocumentExtractionError
from app_common.logging import get_logger, log_json
from app_common.s3_utils import get_object_bytes, put_text


logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    bucket = event["document"]["bucket"]
    key = event["document"]["key"]
    output_bucket = event["artifacts"]["output_bucket"]
    output_prefix = event["artifacts"]["output_prefix"]

    pdf_bytes = get_object_bytes(bucket, key)
    pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_texts = [page.get_text("text").strip() for page in pdf_document]
    document_text = "\n\n".join(text for text in page_texts if text)

    if not document_text.strip():
        raise DocumentExtractionError(
            "No extractable text found with PyMuPDF. OCR support should be added for scanned PDFs."
        )

    raw_text_key = f"{output_prefix}/raw_text.txt"
    put_text(output_bucket, raw_text_key, document_text)

    event["artifacts"]["raw_text"] = {
        "bucket": output_bucket,
        "key": raw_text_key,
    }
    event["pdf_extraction"] = {
        "engine": "pymupdf",
        "page_count": pdf_document.page_count,
        "text_length": len(document_text),
    }

    log_json(
        logger,
        "PDF text extracted",
        request_id=event["request_id"],
        page_count=pdf_document.page_count,
        text_length=len(document_text),
    )
    return event

