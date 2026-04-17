from typing import Any

from app_common.logging import get_logger, log_json
from app_common.validators import validate_schema_output


logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    extracted_data = event["llm_extraction"]["data"]
    profile = event["resolved_profile"]

    validation_errors = validate_schema_output(
        extracted_data=extracted_data,
        schema=profile["schema"],
        validation_rules=profile["validation"],
    )

    event["validation"] = {
        "is_valid": True,
        "errors": validation_errors,
    }

    log_json(logger, "Structured output validated", request_id=event["request_id"])
    return event

