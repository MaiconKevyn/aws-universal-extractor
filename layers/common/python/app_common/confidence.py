import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ConfidenceReport:
    score: float
    abstain_recommended: bool
    threshold: float
    required_field_count: int
    present_required_field_count: int
    missing_required_fields: list[str]
    evidence_field_count: int
    evidence_hit_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_extraction_confidence(
    *,
    extracted_data: dict[str, Any],
    schema: dict[str, Any],
    validation_rules: dict[str, Any],
    document_text: str,
) -> ConfidenceReport:
    threshold = float(validation_rules.get("confidence_threshold", 0.75))
    required_paths = _required_leaf_paths(schema)

    missing = [
        path for path in required_paths
        if _is_empty(_get_path_value(extracted_data, path))
    ]
    present = len(required_paths) - len(missing)
    completeness = present / len(required_paths) if required_paths else 1.0

    evidence_total = 0
    evidence_hits = 0
    for path in required_paths:
        value = _get_path_value(extracted_data, path)
        if _is_empty(value) or isinstance(value, (dict, list)):
            continue
        evidence_total += 1
        if _value_has_evidence(value, document_text):
            evidence_hits += 1

    evidence_score = evidence_hits / evidence_total if evidence_total else 1.0
    score = round((0.7 * completeness) + (0.3 * evidence_score), 3)
    return ConfidenceReport(
        score=score,
        abstain_recommended=score < threshold,
        threshold=threshold,
        required_field_count=len(required_paths),
        present_required_field_count=present,
        missing_required_fields=missing,
        evidence_field_count=evidence_total,
        evidence_hit_count=evidence_hits,
    )


def _required_leaf_paths(schema: dict[str, Any], prefix: str = "") -> list[str]:
    if schema.get("type") == "object" or "properties" in schema:
        paths: list[str] = []
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            child = properties.get(key, {})
            child_prefix = f"{prefix}.{key}" if prefix else key
            child_paths = _required_leaf_paths(child, child_prefix)
            paths.extend(child_paths or [child_prefix])
        return paths

    if schema.get("type") == "array" or "items" in schema:
        return [prefix]

    return [prefix] if prefix else []


def _get_path_value(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def _value_has_evidence(value: Any, document_text: str) -> bool:
    haystack = document_text.casefold()
    if isinstance(value, str):
        cleaned = value.strip()
        return not cleaned or cleaned.casefold() in haystack

    if isinstance(value, (int, float)):
        number = float(value)
        candidates = {
            f"{number:.2f}",
            f"{number:,.2f}",
            str(int(number)) if number.is_integer() else str(number),
        }
        compact_haystack = re.sub(r"[$,\s]", "", haystack)
        return any(c.casefold() in haystack or re.sub(r"[$,\s]", "", c).casefold() in compact_haystack for c in candidates)

    return True
