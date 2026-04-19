from typing import Any

from app_common.config import get_settings
from app_common.logging import get_logger, log_json
from app_common.s3_utils import put_json, s3_uri


logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = get_settings()
    output_bucket = settings.documents_bucket_name or event["artifacts"]["output_bucket"]
    output_prefix = event["artifacts"]["output_prefix"]

    result_key = f"{output_prefix}/result.json"
    status_key = f"{output_prefix}/status.json"
    document_format = event.get("document_format", "unknown")
    text_extraction = (
        event.get("pdf_extraction")
        or event.get("xlsx_extraction")
        or event.get("csv_extraction")
        or event.get("docx_extraction")
        or {}
    )
    artifacts = event["artifacts"]
    artifacts["output_bucket"] = output_bucket
    artifacts["result"] = {"bucket": output_bucket, "key": result_key}
    artifacts["status"] = {"bucket": output_bucket, "key": status_key}

    result_payload = {
        "request_id": event["request_id"],
        "status": "SUCCEEDED",
        "submitted_at": event.get("submitted_at"),
        "document": event["document"],
        "document_format": document_format,
        "document_metadata": event.get("document_metadata", {}),
        "extraction_profile": event["extraction_profile"],
        "client_id": event.get("client_id"),
        "document_id": event.get("document_id"),
        "metadata": event.get("metadata", {}),
        "text_extraction": text_extraction,
        "llm": {
            "model": event["llm_extraction"]["model"],
            "response_id": event["llm_extraction"]["response_id"],
            "usage": event["llm_extraction"]["usage"],
            "usage_metrics": event["llm_extraction"].get("usage_metrics", {}),
            "cache": event["llm_extraction"].get("cache", {}),
            "chunking": event["llm_extraction"].get("chunking", {}),
            "confidence": event["llm_extraction"].get("confidence", {}),
            "prompt_safety": event["llm_extraction"].get("prompt_safety", {}),
        },
        "extracted_data": event["llm_extraction"]["data"],
        "validation": event.get("validation", {}),
        "artifacts": artifacts,
    }
    status_payload = {
        "request_id": event["request_id"],
        "status": "SUCCEEDED",
        "submitted_at": event.get("submitted_at"),
        "document": event["document"],
        "document_format": document_format,
        "extraction_profile": event["extraction_profile"],
        "result_uri": s3_uri(output_bucket, result_key),
        "artifacts": artifacts,
    }

    put_json(output_bucket, result_key, result_payload)
    put_json(output_bucket, status_key, status_payload)

    log_json(
        logger,
        "Extraction result persisted",
        request_id=event["request_id"],
        result_uri=s3_uri(output_bucket, result_key),
    )
    return event
