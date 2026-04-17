import json
from typing import Any

from jsonschema import ValidationError, validate

from app_common.exceptions import RequestValidationError, StructuredOutputValidationError


def validate_submission_payload(payload: dict[str, Any]) -> dict[str, Any]:
    document = payload.get("document")
    extraction_profile = payload.get("extraction_profile")

    if not isinstance(document, dict):
        raise RequestValidationError("document must be an object")

    if not document.get("bucket") or not document.get("key"):
        raise RequestValidationError("document.bucket and document.key are required")

    if not isinstance(extraction_profile, dict):
        raise RequestValidationError("extraction_profile must be an object")

    if not extraction_profile.get("id") or not extraction_profile.get("version"):
        raise RequestValidationError("extraction_profile.id and extraction_profile.version are required")

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise RequestValidationError("metadata must be an object when provided")

    return payload


def validate_schema_output(
    extracted_data: dict[str, Any],
    schema: dict[str, Any],
    validation_rules: dict[str, Any],
) -> list[str]:
    try:
        validate(instance=extracted_data, schema=schema)
    except ValidationError as error:
        raise StructuredOutputValidationError(error.message) from error

    errors: list[str] = []
    for field_name in validation_rules.get("required_non_empty_fields", []):
        value = extracted_data.get(field_name)
        if value in (None, "", [], {}):
            errors.append(f"Field {field_name} must be non-empty")

    if errors:
        raise StructuredOutputValidationError("; ".join(errors))

    return errors


def to_metadata_json(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=True, sort_keys=True)

