from typing import Any

from app_common.logging import get_logger, log_json
from app_common.s3_utils import put_json, s3_uri


logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    output_bucket = event["artifacts"]["output_bucket"]
    output_prefix = event["artifacts"]["output_prefix"]
    status_key = f"{output_prefix}/status.json"
    error_payload = event.get("error", {})

    status_payload = {
        "request_id": event["request_id"],
        "status": "FAILED",
        "error": error_payload,
    }

    put_json(output_bucket, status_key, status_payload)

    log_json(
        logger,
        "Extraction failed",
        request_id=event["request_id"],
        status_uri=s3_uri(output_bucket, status_key),
        error=error_payload,
    )

    event["artifacts"]["status"] = {"bucket": output_bucket, "key": status_key}
    return event

