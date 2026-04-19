import json
import os
import re
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from app_common.config import get_settings, load_secret
from app_common.llm_errors import OpenAINonRetryableError, OpenAIResponseError, OpenAIRetryableError


def _render_template(template: str, context: dict[str, Any]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def _schema_name(profile_id: str, profile_version: str) -> str:
    raw_name = f"{profile_id}_{profile_version}"
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw_name)[:64]


def _classify_openai_error(error: Exception) -> Exception:
    if isinstance(error, (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)):
        return OpenAIRetryableError(str(error))

    if isinstance(error, (AuthenticationError, BadRequestError, PermissionDeniedError)):
        return OpenAINonRetryableError(str(error))

    if isinstance(error, APIStatusError):
        status_code = getattr(error, "status_code", None)
        if status_code in {408, 409, 429, 500, 502, 503, 504}:
            return OpenAIRetryableError(str(error))
        return OpenAINonRetryableError(str(error))

    return error


class OpenAIExtractionClient:
    def __init__(self) -> None:
        settings = get_settings()
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key and settings.openai_api_key_secret_arn:
            api_key = load_secret(settings.openai_api_key_secret_arn)

        if not api_key:
            raise ValueError("OPENAI_API_KEY or OPENAI_API_KEY_SECRET_ARN must be configured")

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if settings.openai_base_url:
            client_kwargs["base_url"] = settings.openai_base_url

        self.client = OpenAI(**client_kwargs)
        self.model = settings.openai_model

    def extract(
        self,
        profile: dict[str, Any],
        document_text: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        user_prompt = _render_template(profile["prompt"]["user_template"], context)
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": profile["prompt"]["system"]},
                    {"role": "user", "content": user_prompt},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": _schema_name(profile["id"], profile["version"]),
                        "schema": profile["schema"],
                        "strict": bool(profile["validation"].get("strict_schema", True)),
                    }
                },
            )
        except Exception as error:
            raise _classify_openai_error(error) from error

        output_text = getattr(response, "output_text", None)
        if not output_text:
            raise OpenAIResponseError("OpenAI response did not include output_text")

        try:
            parsed_output = json.loads(output_text)
        except json.JSONDecodeError as error:
            raise OpenAIResponseError("OpenAI response output_text was not valid JSON") from error
        usage = getattr(response, "usage", None)
        usage_payload = usage.model_dump() if hasattr(usage, "model_dump") else usage

        return {
            "response_id": response.id,
            "model": getattr(response, "model", self.model),
            "usage": usage_payload or {},
            "data": parsed_output,
            "raw_output": output_text,
        }
