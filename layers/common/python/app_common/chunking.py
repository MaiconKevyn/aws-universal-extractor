import json
import math
from typing import Any


def approximate_token_count(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def chunk_text(text: str, *, max_chars: int, overlap_chars: int = 0) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            newline = text.rfind("\n\n", start, hard_end)
            if newline > start + max_chars // 2:
                end = newline

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break
        next_start = end - overlap_chars if overlap_chars > 0 else end
        start = next_start if next_start > start else end

    return chunks


def merge_extraction_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for output in outputs:
        merged = _merge_values(merged, output)
    return merged


def _merge_values(left: Any, right: Any) -> Any:
    if _is_empty(left):
        return right
    if _is_empty(right):
        return left

    if isinstance(left, dict) and isinstance(right, dict):
        merged = dict(left)
        for key, value in right.items():
            merged[key] = _merge_values(merged.get(key), value)
        return merged

    if isinstance(left, list) and isinstance(right, list):
        seen: set[str] = set()
        merged_list: list[Any] = []
        for item in left + right:
            marker = json.dumps(item, sort_keys=True, default=str)
            if marker in seen:
                continue
            seen.add(marker)
            merged_list.append(item)
        return merged_list

    return left


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})
