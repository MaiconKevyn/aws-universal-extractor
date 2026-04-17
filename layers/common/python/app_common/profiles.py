from pathlib import Path
from typing import Any

import yaml

from app_common.exceptions import ProfileNotFoundError, ProfileValidationError


def profile_file_path(profiles_root: str, profile_id: str, version: str) -> Path:
    return Path(profiles_root) / profile_id / f"{version}.yml"


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    required_top_level = ("id", "version", "prompt", "schema", "validation")
    missing = [field for field in required_top_level if field not in profile]
    if missing:
        raise ProfileValidationError(f"Profile is missing required keys: {missing}")

    prompt = profile["prompt"]
    if "system" not in prompt or "user_template" not in prompt:
        raise ProfileValidationError("Profile prompt must contain system and user_template")

    schema = profile["schema"]
    if schema.get("type") != "object":
        raise ProfileValidationError("Profile schema root type must be object")

    if schema.get("additionalProperties") is not False:
        raise ProfileValidationError(
            "Profile schema must define additionalProperties: false at the root"
        )

    return profile


def load_profile(profiles_root: str, profile_id: str, version: str) -> dict[str, Any]:
    path = profile_file_path(profiles_root, profile_id, version)
    if not path.exists():
        raise ProfileNotFoundError(f"Profile not found: {path}")

    with path.open("r", encoding="utf-8") as file_handle:
        profile = yaml.safe_load(file_handle)

    if not isinstance(profile, dict):
        raise ProfileValidationError(f"Profile file is not a mapping: {path}")

    return validate_profile(profile)

