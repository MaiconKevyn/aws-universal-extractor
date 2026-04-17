from typing import Any

from app_common.config import get_settings
from app_common.logging import get_logger, log_json
from app_common.s3_utils import head_object


logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = get_settings()
    bucket = event["document"]["bucket"]
    key = event["document"]["key"]

    if settings.documents_bucket_name and bucket != settings.documents_bucket_name:
        raise ValueError(
            f"Document bucket {bucket} does not match configured bucket {settings.documents_bucket_name}"
        )

    metadata = head_object(bucket, key)
    last_modified = metadata.get("LastModified")
    event["document_metadata"] = {
        "content_length": metadata.get("ContentLength"),
        "content_type": metadata.get("ContentType"),
        "etag": metadata.get("ETag"),
        "last_modified": last_modified.isoformat() if last_modified else None,
    }

    log_json(logger, "Document located", bucket=bucket, key=key, request_id=event["request_id"])
    return event
