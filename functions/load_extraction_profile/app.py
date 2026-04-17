from typing import Any

from app_common.config import get_settings
from app_common.logging import get_logger, log_json
from app_common.profiles import load_profile


logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = get_settings()
    profile_id = event["extraction_profile"]["id"]
    version = event["extraction_profile"]["version"]
    profile = load_profile(settings.profiles_root, profile_id, version)
    event["resolved_profile"] = profile

    log_json(
        logger,
        "Extraction profile loaded",
        request_id=event["request_id"],
        profile_id=profile_id,
        version=version,
    )
    return event

