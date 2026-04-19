import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3


def truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def document_hash(document_text: str) -> str:
    return hashlib.sha256(document_text.encode("utf-8")).hexdigest()


def build_extraction_cache_key(
    *,
    document_text: str,
    profile: dict[str, Any],
    model: str,
) -> str:
    return stable_hash(
        {
            "document_sha256": document_hash(document_text),
            "profile_id": profile.get("id"),
            "profile_version": profile.get("version"),
            "prompt": profile.get("prompt"),
            "schema": profile.get("schema"),
            "validation": profile.get("validation"),
            "model": model,
        }
    )


class ExtractionCache:
    def __init__(self) -> None:
        self.table_name = os.getenv("EXTRACTION_CACHE_TABLE", "")
        self.enabled = bool(self.table_name) and truthy(os.getenv("ENABLE_LLM_CACHE"), default=True)
        self._table = None

    @property
    def table(self):
        if self._table is None:
            self._table = boto3.resource("dynamodb").Table(self.table_name)
        return self._table

    def get(self, cache_key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            response = self.table.get_item(Key={"cache_key": cache_key}, ConsistentRead=False)
        except Exception:
            return None
        item = response.get("Item")
        if not item:
            return None
        payload = item.get("llm_result_json")
        if not payload:
            return None
        return {
            "cache_key": cache_key,
            "created_at": item.get("created_at"),
            "document_sha256": item.get("document_sha256"),
            "llm_result": json.loads(payload),
        }

    def put(
        self,
        *,
        cache_key: str,
        document_sha256: str,
        profile: dict[str, Any],
        model: str,
        llm_result: dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        now = datetime.now(UTC)
        ttl_days = int(os.getenv("LLM_CACHE_TTL_DAYS", "30"))
        llm_result_json = json.dumps(llm_result, ensure_ascii=True, default=str)
        if len(llm_result_json.encode("utf-8")) > 350_000:
            return
        try:
            self.table.put_item(
                Item={
                    "cache_key": cache_key,
                    "created_at": now.isoformat(),
                    "expires_at": int((now + timedelta(days=ttl_days)).timestamp()),
                    "document_sha256": document_sha256,
                    "profile_id": profile.get("id", ""),
                    "profile_version": profile.get("version", ""),
                    "model": model,
                    "llm_result_json": llm_result_json,
                }
            )
        except Exception:
            return
