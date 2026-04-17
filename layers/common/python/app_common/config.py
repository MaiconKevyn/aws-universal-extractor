import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    documents_bucket_name: str
    openai_api_key_secret_arn: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    state_machine_arn: str
    stage_name: str
    profiles_root: str


def default_profiles_root() -> str:
    explicit_root = os.getenv("PROFILES_ROOT")
    if explicit_root:
        return explicit_root

    lambda_task_root = os.getenv("LAMBDA_TASK_ROOT")
    if lambda_task_root:
        return str(Path(lambda_task_root) / "profiles")

    return str(Path.cwd() / "profiles")


def get_settings() -> Settings:
    return Settings(
        documents_bucket_name=os.getenv("DOCUMENTS_BUCKET_NAME", ""),
        openai_api_key_secret_arn=os.getenv("OPENAI_API_KEY_SECRET_ARN", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        openai_base_url=os.getenv("OPENAI_BASE_URL"),
        state_machine_arn=os.getenv("STATE_MACHINE_ARN", ""),
        stage_name=os.getenv("STAGE_NAME", "dev"),
        profiles_root=default_profiles_root(),
    )


def load_secret(secret_arn: str) -> str:
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    secret_string = response.get("SecretString", "")

    if not secret_string:
        raise ValueError(f"Secret {secret_arn} does not contain SecretString")

    try:
        parsed_secret: Any = json.loads(secret_string)
    except json.JSONDecodeError:
        return secret_string

    if isinstance(parsed_secret, dict):
        for key in ("OPENAI_API_KEY", "api_key", "openai_api_key"):
            if parsed_secret.get(key):
                return parsed_secret[key]

    raise ValueError(
        f"Secret {secret_arn} must be a plain string or a JSON object containing OPENAI_API_KEY"
    )
