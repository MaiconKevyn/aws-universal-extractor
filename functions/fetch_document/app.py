from pathlib import PurePosixPath
from typing import Any

from app_common.config import get_settings
from app_common.logging import get_logger, log_json
from app_common.s3_utils import head_object


logger = get_logger(__name__)


EXTENSION_MAP: dict[str, str] = {
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".docx": "docx",
    ".csv": "csv",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
}

CONTENT_TYPE_MAP: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/csv": "csv",
    "image/png": "png",
    "image/jpeg": "jpg",
}


def _detect_format(key: str, content_type: str | None) -> str:
    ext = PurePosixPath(key).suffix.lower()
    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext]
    if content_type:
        normalized = content_type.split(";")[0].strip().lower()
        if normalized in CONTENT_TYPE_MAP:
            return CONTENT_TYPE_MAP[normalized]
    return "unknown"


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
    content_type = metadata.get("ContentType")
    event["document_metadata"] = {
        "content_length": metadata.get("ContentLength"),
        "content_type": content_type,
        "etag": metadata.get("ETag"),
        "last_modified": last_modified.isoformat() if last_modified else None,
    }
    event["document_format"] = _detect_format(key, content_type)

    log_json(
        logger,
        "Document located",
        bucket=bucket,
        key=key,
        request_id=event["request_id"],
        document_format=event["document_format"],
    )
    return event
