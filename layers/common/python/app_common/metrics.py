"""CloudWatch metrics emission for the extraction pipeline.

Fire-and-forget: every public function logs on failure but never raises,
so a CloudWatch outage cannot break the extraction pipeline.

Namespace: UniversalExtractor
Common dimensions: Stage, Format, Profile
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .logging import get_logger

logger = get_logger(__name__)

NAMESPACE = "UniversalExtractor"

_cw_client: Any = None


def _client() -> Any:
    global _cw_client
    if _cw_client is None:
        _cw_client = boto3.client("cloudwatch")
    return _cw_client


def _stage() -> str:
    return os.environ.get("STAGE_NAME", "unknown")


def _base_dims(*, fmt: str, profile_id: str) -> list[dict[str, str]]:
    return [
        {"Name": "Stage", "Value": _stage()},
        {"Name": "Format", "Value": fmt or "unknown"},
        {"Name": "Profile", "Value": profile_id or "unknown"},
    ]


def _agg_dims() -> list[dict[str, str]]:
    """Stage-only dimensions for aggregate alarms and dashboard panels."""
    return [{"Name": "Stage", "Value": _stage()}]


def _put(metric_data: list[dict[str, Any]]) -> None:
    if not metric_data:
        return
    try:
        _client().put_metric_data(Namespace=NAMESPACE, MetricData=metric_data)
    except ClientError as exc:
        logger.warning("CloudWatch put_metric_data failed: %s", exc)
    except Exception as exc:
        logger.warning("CloudWatch unexpected error: %s", exc)


def emit_extraction_success(
    *,
    fmt: str,
    profile_id: str,
    duration_seconds: float,
    cost_usd: float | None,
    input_tokens: int,
    output_tokens: int,
    confidence_score: float | None,
    fields_null_count: int,
    gross_pay: float | None,
    net_pay: float | None,
    pdf_strategy: str | None = None,
) -> None:
    dims = _base_dims(fmt=fmt, profile_id=profile_id)
    now = datetime.now(timezone.utc)

    data: list[dict[str, Any]] = [
        {"MetricName": "ExtractionSuccess",          "Dimensions": dims, "Value": 1.0,                   "Unit": "Count",   "Timestamp": now},
        {"MetricName": "ExtractionDurationSeconds",  "Dimensions": dims, "Value": duration_seconds,       "Unit": "Seconds", "Timestamp": now},
        {"MetricName": "FieldsNullCount",            "Dimensions": dims, "Value": float(fields_null_count), "Unit": "Count", "Timestamp": now},
        {"MetricName": "LLMInputTokens",             "Dimensions": dims, "Value": float(input_tokens),    "Unit": "Count",   "Timestamp": now},
        {"MetricName": "LLMOutputTokens",            "Dimensions": dims, "Value": float(output_tokens),   "Unit": "Count",   "Timestamp": now},
    ]

    if cost_usd is not None:
        data.append({"MetricName": "LLMCostUSD", "Dimensions": dims, "Value": cost_usd, "Unit": "None", "Timestamp": now})

    if confidence_score is not None:
        data.append({"MetricName": "ConfidenceScore", "Dimensions": dims, "Value": confidence_score, "Unit": "None", "Timestamp": now})

    if gross_pay is not None:
        data.append({"MetricName": "GrossPayValue", "Dimensions": dims, "Value": gross_pay, "Unit": "None", "Timestamp": now})

    if net_pay is not None:
        data.append({"MetricName": "NetPayValue", "Dimensions": dims, "Value": net_pay, "Unit": "None", "Timestamp": now})

    if pdf_strategy:
        strategy_dims = dims + [{"Name": "Strategy", "Value": pdf_strategy}]
        data.append({"MetricName": "PDFExtractionStrategy", "Dimensions": strategy_dims, "Value": 1.0, "Unit": "Count", "Timestamp": now})

    # Aggregate (Stage-only) metrics for alarms and dashboard panels
    agg = _agg_dims()
    data.extend([
        {"MetricName": "ExtractionSuccess",        "Dimensions": agg, "Value": 1.0,                     "Unit": "Count",   "Timestamp": now},
        {"MetricName": "ExtractionDurationSeconds", "Dimensions": agg, "Value": duration_seconds,         "Unit": "Seconds", "Timestamp": now},
        {"MetricName": "LLMInputTokens",            "Dimensions": agg, "Value": float(input_tokens),      "Unit": "Count",   "Timestamp": now},
        {"MetricName": "LLMOutputTokens",           "Dimensions": agg, "Value": float(output_tokens),     "Unit": "Count",   "Timestamp": now},
        {"MetricName": "FieldsNullCount",           "Dimensions": agg, "Value": float(fields_null_count), "Unit": "Count",   "Timestamp": now},
    ])
    if cost_usd is not None:
        data.append({"MetricName": "LLMCostUSD",      "Dimensions": agg, "Value": cost_usd,         "Unit": "None", "Timestamp": now})
    if confidence_score is not None:
        data.append({"MetricName": "ConfidenceScore", "Dimensions": agg, "Value": confidence_score, "Unit": "None", "Timestamp": now})
    if gross_pay is not None:
        data.append({"MetricName": "GrossPayValue",   "Dimensions": agg, "Value": gross_pay,         "Unit": "None", "Timestamp": now})
    if net_pay is not None:
        data.append({"MetricName": "NetPayValue",     "Dimensions": agg, "Value": net_pay,           "Unit": "None", "Timestamp": now})

    _put(data)


def emit_extraction_failure(
    *,
    fmt: str,
    profile_id: str,
    failure_stage: str = "unknown",
) -> None:
    dims = _base_dims(fmt=fmt, profile_id=profile_id)
    stage_dims = dims + [{"Name": "FailureStage", "Value": failure_stage}]
    now = datetime.now(timezone.utc)

    _put([
        {"MetricName": "ExtractionFailure",        "Dimensions": dims,        "Value": 1.0, "Unit": "Count", "Timestamp": now},
        {"MetricName": "ExtractionFailureByStage", "Dimensions": stage_dims,  "Value": 1.0, "Unit": "Count", "Timestamp": now},
        {"MetricName": "ExtractionFailure",        "Dimensions": _agg_dims(), "Value": 1.0, "Unit": "Count", "Timestamp": now},
    ])


def emit_business_rules(
    *,
    fmt: str,
    profile_id: str,
    passed: bool,
    score: float,
    violation_count: int,
) -> None:
    dims = _base_dims(fmt=fmt, profile_id=profile_id)
    now = datetime.now(timezone.utc)

    agg = _agg_dims()
    _put([
        {"MetricName": "BusinessRulesPassed",        "Dimensions": dims, "Value": 1.0 if passed else 0.0, "Unit": "None",  "Timestamp": now},
        {"MetricName": "BusinessRulesScore",         "Dimensions": dims, "Value": score,                  "Unit": "None",  "Timestamp": now},
        {"MetricName": "BusinessRulesViolationCount","Dimensions": dims, "Value": float(violation_count),  "Unit": "Count", "Timestamp": now},
        {"MetricName": "BusinessRulesPassed",        "Dimensions": agg,  "Value": 1.0 if passed else 0.0, "Unit": "None",  "Timestamp": now},
        {"MetricName": "BusinessRulesScore",         "Dimensions": agg,  "Value": score,                  "Unit": "None",  "Timestamp": now},
    ])
