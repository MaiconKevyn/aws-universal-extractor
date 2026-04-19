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

    result_payload = {
        "request_id": event["request_id"],
        "status": "SUCCEEDED",
        "document": event["document"],
        "document_metadata": event.get("document_metadata", {}),
        "extraction_profile": event["extraction_profile"],
        "client_id": event.get("client_id"),
        "document_id": event.get("document_id"),
        "metadata": event.get("metadata", {}),
        "pdf_extraction": event.get("pdf_extraction", {}),
        "llm": {
            "model": event["llm_extraction"]["model"],
            "response_id": event["llm_extraction"]["response_id"],
            "usage": event["llm_extraction"]["usage"],
        },
        "extracted_data": event["llm_extraction"]["data"],
        "validation": event.get("validation", {}),
        "artifacts": event["artifacts"],
    }
    status_payload = {
        "request_id": event["request_id"],
        "status": "SUCCEEDED",
        "result_uri": s3_uri(output_bucket, result_key),
    }

    put_json(output_bucket, result_key, result_payload)
    put_json(output_bucket, status_key, status_payload)

    event["artifacts"]["output_bucket"] = output_bucket
    event["artifacts"]["result"] = {"bucket": output_bucket, "key": result_key}
    event["artifacts"]["status"] = {"bucket": output_bucket, "key": status_key}

    log_json(
        logger,
        "Extraction result persisted",
        request_id=event["request_id"],
        result_uri=s3_uri(output_bucket, result_key),
    )
    return event
