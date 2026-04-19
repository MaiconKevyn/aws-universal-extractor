import os
from typing import Any

from app_common.exceptions import StructuredOutputValidationError
from app_common.logging import get_logger, log_json
from app_common.validators import validate_schema_output


logger = get_logger(__name__)


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    extracted_data = event["llm_extraction"]["data"]
    profile = event["resolved_profile"]

    validation_errors = validate_schema_output(
        extracted_data=extracted_data,
        schema=profile["schema"],
        validation_rules=profile["validation"],
    )

    confidence = event["llm_extraction"].get("confidence") or {}
    if _truthy(os.getenv("ENABLE_CONFIDENCE_GATE"), default=False) and confidence.get("abstain_recommended"):
        raise StructuredOutputValidationError(
            f"Extraction confidence {confidence.get('score')} is below threshold {confidence.get('threshold')}"
        )

    event["validation"] = {
        "is_valid": True,
        "errors": validation_errors,
        "confidence": confidence,
    }

    log_json(logger, "Structured output validated", request_id=event["request_id"])
    return event
