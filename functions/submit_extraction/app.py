import json
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import boto3

from app_common.config import get_settings
from app_common.exceptions import RequestValidationError
from app_common.logging import get_logger, log_json
from app_common.s3_utils import derive_output_prefix, s3_uri
from app_common.validators import validate_submission_payload


logger = get_logger(__name__)
stepfunctions_client = boto3.client("stepfunctions")


def _json_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if body is None:
        return event

    if isinstance(body, str):
        return json.loads(body)

    return body


def _request_id(payload: dict[str, Any]) -> str:
    return payload.get("request_id") or f"req_{uuid.uuid4().hex[:24]}"


def _execution_name(request_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", request_id)[:80]


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = get_settings()

    try:
        payload = _json_body(event)
        validate_submission_payload(payload)
    except (json.JSONDecodeError, RequestValidationError) as error:
        log_json(logger, "Invalid extraction submission", error=str(error))
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "invalid_request", "message": str(error)}),
        }

    request_id = _request_id(payload)
    document_bucket = payload["document"]["bucket"]
    document_key = payload["document"]["key"]
    output_bucket = settings.documents_bucket_name or document_bucket

    if settings.documents_bucket_name and document_bucket != settings.documents_bucket_name:
        message = (
            f"document.bucket must be {settings.documents_bucket_name}; "
            f"received {document_bucket}"
        )
        log_json(
            logger,
            "Invalid document bucket",
            request_id=request_id,
            expected_bucket=settings.documents_bucket_name,
            received_bucket=document_bucket,
        )
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"status": "invalid_request", "message": message}),
        }

    profile_id = payload["extraction_profile"]["id"]
    profile_version = payload["extraction_profile"]["version"]
    output_prefix = derive_output_prefix(document_key, profile_id, profile_version, request_id)

    state_input = {
        **payload,
        "request_id": request_id,
        "submitted_at": datetime.now(UTC).isoformat(),
        "artifacts": {
            "input_document_uri": s3_uri(document_bucket, document_key),
            "output_bucket": output_bucket,
            "output_prefix": output_prefix,
        },
    }

    execution = stepfunctions_client.start_execution(
        stateMachineArn=settings.state_machine_arn,
        name=_execution_name(request_id),
        input=json.dumps(state_input),
    )

    log_json(
        logger,
        "Extraction triggered",
        request_id=request_id,
        execution_arn=execution["executionArn"],
        bucket=document_bucket,
        key=document_key,
    )

    return {
        "statusCode": 202,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "status": "accepted",
                "request_id": request_id,
                "execution_arn": execution["executionArn"],
                "message": "Extraction triggered successfully",
                "output_prefix": s3_uri(output_bucket, output_prefix),
            }
        ),
    }
