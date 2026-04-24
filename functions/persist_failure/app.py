from typing import Any

from app_common.config import get_settings
from app_common.logging import get_logger, log_json
from app_common.metrics import emit_extraction_failure
from app_common.s3_utils import put_json, s3_uri


logger = get_logger(__name__)


def _failure_stage(error: dict[str, Any]) -> str:
    """Best-effort extraction of which state caused the failure."""
    cause = error.get("Cause") or error.get("cause") or ""
    err = error.get("Error") or error.get("error") or ""
    # Step Functions wraps Lambda errors as {"Error": "...", "Cause": "{\"errorType\":...}"}
    for token in (err, cause):
        if token:
            return str(token)[:64]
    return "unknown"


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = get_settings()
    output_bucket = settings.documents_bucket_name or event["artifacts"]["output_bucket"]
    output_prefix = event["artifacts"]["output_prefix"]
    error_key = f"{output_prefix}/error.json"
    status_key = f"{output_prefix}/status.json"
    error_payload = event.get("error", {})
    artifacts = event["artifacts"]
    artifacts["output_bucket"] = output_bucket
    artifacts["error"] = {"bucket": output_bucket, "key": error_key}
    artifacts["status"] = {"bucket": output_bucket, "key": status_key}

    failure_payload = {
        "request_id": event["request_id"],
        "status": "FAILED",
        "submitted_at": event.get("submitted_at"),
        "document": event.get("document"),
        "document_format": event.get("document_format"),
        "document_metadata": event.get("document_metadata", {}),
        "extraction_profile": event.get("extraction_profile"),
        "client_id": event.get("client_id"),
        "document_id": event.get("document_id"),
        "metadata": event.get("metadata", {}),
        "llm_extraction": event.get("llm_extraction", {}),
        "error": error_payload,
        "artifacts": artifacts,
    }

    status_payload = {
        "request_id": event["request_id"],
        "status": "FAILED",
        "submitted_at": event.get("submitted_at"),
        "document": event.get("document"),
        "document_format": event.get("document_format"),
        "extraction_profile": event.get("extraction_profile"),
        "error": error_payload,
        "error_uri": s3_uri(output_bucket, error_key),
        "artifacts": artifacts,
    }

    put_json(output_bucket, error_key, failure_payload)
    put_json(output_bucket, status_key, status_payload)

    log_json(
        logger,
        "Extraction failed",
        request_id=event["request_id"],
        status_uri=s3_uri(output_bucket, status_key),
        error=error_payload,
    )

    # --- metrics ---
    profile = event.get("extraction_profile") or {}
    emit_extraction_failure(
        fmt=event.get("document_format") or "unknown",
        profile_id=profile.get("id", "unknown"),
        failure_stage=_failure_stage(error_payload),
    )

    return event
