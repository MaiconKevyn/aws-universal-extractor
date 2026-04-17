import json
import posixpath
from typing import Any

import boto3


_s3_client = boto3.client("s3")


def s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def normalize_s3_key(key: str) -> str:
    return key.lstrip("/")


def derive_output_prefix(
    document_key: str,
    profile_id: str,
    profile_version: str,
    request_id: str,
) -> str:
    clean_key = normalize_s3_key(document_key)
    parent_prefix = posixpath.dirname(clean_key)
    parts = [parent_prefix, "extract", profile_id, profile_version, request_id]
    return posixpath.join(*[part for part in parts if part])


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

