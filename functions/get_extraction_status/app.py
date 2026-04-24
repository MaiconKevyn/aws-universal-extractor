"""Status polling endpoint for async extractions.

GET /extractions/{request_id}
  202  RUNNING   — execution still in progress
  200  SUCCEEDED — full status.json payload from S3
  200  FAILED    — error payload from S3 (or Step Functions fallback)
  404            — execution does not exist
"""
from __future__ import annotations

import json
import re
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app_common.config import get_settings
from app_common.logging import get_logger, log_json
from app_common.s3_utils import get_object_text


logger = get_logger(__name__)
_sfn = boto3.client("stepfunctions")

_CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}


def _execution_name(request_id: str) -> str:
    # Mirror the sanitisation in submit_extraction so we reconstruct the same name.
    return re.sub(r"[^A-Za-z0-9_-]", "_", request_id)[:80]


def _execution_arn(state_machine_arn: str, execution_name: str) -> str:
    # arn:aws:states:r:a:stateMachine:n  →  arn:aws:states:r:a:execution:n:<exec>
    return state_machine_arn.replace(":stateMachine:", ":execution:") + ":" + execution_name


def _resp(code: int, body: Any) -> dict[str, Any]:
    return {"statusCode": code, "headers": _CORS, "body": json.dumps(body, default=str)}


def _read_s3_json(bucket: str, key: str) -> dict[str, Any] | None:
    try:
        return json.loads(get_object_text(bucket, key))
    except Exception:
        return None


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = (event.get("pathParameters") or {}).get("request_id", "")
    if not request_id:
        return _resp(400, {"error": "request_id path parameter is required"})

    settings = get_settings()
    exec_arn = _execution_arn(settings.state_machine_arn, _execution_name(request_id))

    try:
        execution = _sfn.describe_execution(executionArn=exec_arn)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ExecutionDoesNotExist":
            return _resp(404, {"error": "not found", "request_id": request_id})
        raise

    status = execution["status"]  # RUNNING | SUCCEEDED | FAILED | TIMED_OUT | ABORTED
    log_json(logger, "Execution status queried", request_id=request_id, status=status)

    if status == "RUNNING":
        return _resp(202, {
            "status": "RUNNING",
            "request_id": request_id,
            "started_at": execution["startDate"].isoformat(),
        })

    # Execution finished — try to return the richer S3 payload
    output_raw = execution.get("output") or "{}"
    artifacts = json.loads(output_raw).get("artifacts", {})
    bucket = artifacts.get("output_bucket", "")

    if status == "SUCCEEDED":
        s3_key = (artifacts.get("status") or {}).get("key", "")
        if bucket and s3_key:
            payload = _read_s3_json(bucket, s3_key)
            if payload:
                return _resp(200, payload)

    if status == "FAILED":
        s3_key = (artifacts.get("error") or {}).get("key", "")
        if bucket and s3_key:
            payload = _read_s3_json(bucket, s3_key)
            if payload:
                return _resp(200, payload)

    # Fallback: synthesise response from Step Functions metadata alone
    body: dict[str, Any] = {"status": status, "request_id": request_id}
    if execution.get("stopDate"):
        body["stopped_at"] = execution["stopDate"].isoformat()
    if execution.get("cause"):
        body["cause"] = execution["cause"]
    return _resp(200, body)
