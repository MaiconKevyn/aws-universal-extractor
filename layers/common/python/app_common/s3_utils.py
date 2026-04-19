import json
import posixpath
import re
from datetime import UTC, datetime
from typing import Any

import boto3


_s3_client = boto3.client("s3")
_SAFE_PATH_PART_RE = re.compile(r"[^A-Za-z0-9._=-]+")


def s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def normalize_s3_key(key: str) -> str:
    return key.lstrip("/")


def _safe_path_part(value: str) -> str:
    part = _SAFE_PATH_PART_RE.sub("_", value.strip()).strip("_")
    return part or "unknown"


def _date_parts(timestamp: str | None) -> tuple[str, str, str]:
    if not timestamp:
        current = datetime.now(UTC)
    else:
        current = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return f"{current.year:04d}", f"{current.month:02d}", f"{current.day:02d}"


def derive_output_prefix(
    profile_id: str,
    profile_version: str,
    request_id: str,
    submitted_at: str | None = None,
) -> str:
    year, month, day = _date_parts(submitted_at)
    return posixpath.join(
        "runs",
        _safe_path_part(profile_id),
        _safe_path_part(profile_version),
        year,
        month,
        day,
        _safe_path_part(request_id),
    )


def head_object(bucket: str, key: str) -> dict[str, Any]:
    return _s3_client.head_object(Bucket=bucket, Key=key)


def get_object_bytes(bucket: str, key: str) -> bytes:
    response = _s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def get_object_text(bucket: str, key: str) -> str:
    return get_object_bytes(bucket, key).decode("utf-8")


def put_text(bucket: str, key: str, text: str, content_type: str = "text/plain") -> None:
    _s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=text.encode("utf-8"),
        ContentType=content_type,
    )


def put_json(bucket: str, key: str, payload: dict[str, Any]) -> None:
    put_text(
        bucket=bucket,
        key=key,
        text=json.dumps(payload, ensure_ascii=True, indent=2, default=str),
        content_type="application/json",
    )
