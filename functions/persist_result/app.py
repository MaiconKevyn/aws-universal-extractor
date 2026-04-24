from datetime import datetime, timezone
from typing import Any

from app_common.config import get_settings
from app_common.logging import get_logger, log_json
from app_common.metrics import emit_extraction_success
from app_common.s3_utils import put_json, s3_uri


logger = get_logger(__name__)


def _count_nulls(obj: Any) -> int:
    if obj is None:
        return 1
    if isinstance(obj, dict):
        return sum(_count_nulls(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_nulls(item) for item in obj)
    return 0


def _duration_seconds(submitted_at: str | None) -> float:
    if not submitted_at:
        return 0.0
    try:
        start = datetime.fromisoformat(submitted_at)
        return (datetime.now(timezone.utc) - start).total_seconds()
    except Exception:
        return 0.0


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    settings = get_settings()
    output_bucket = settings.documents_bucket_name or event["artifacts"]["output_bucket"]
    output_prefix = event["artifacts"]["output_prefix"]

    result_key = f"{output_prefix}/result.json"
    status_key = f"{output_prefix}/status.json"
    document_format = event.get("document_format", "unknown")
    text_extraction = (
        event.get("pdf_extraction")
        or event.get("xlsx_extraction")
        or event.get("csv_extraction")
        or event.get("docx_extraction")
        or {}
    )
    artifacts = event["artifacts"]
    artifacts["output_bucket"] = output_bucket
    artifacts["result"] = {"bucket": output_bucket, "key": result_key}
    artifacts["status"] = {"bucket": output_bucket, "key": status_key}

    llm = event["llm_extraction"]
    extracted_data = llm["data"]
    usage_metrics = llm.get("usage_metrics", {})
    confidence = llm.get("confidence", {})
    totals = extracted_data.get("totals") or {} if isinstance(extracted_data, dict) else {}

    result_payload = {
        "request_id": event["request_id"],
        "status": "SUCCEEDED",
        "submitted_at": event.get("submitted_at"),
        "document": event["document"],
        "document_format": document_format,
        "document_metadata": event.get("document_metadata", {}),
        "extraction_profile": event["extraction_profile"],
        "client_id": event.get("client_id"),
        "document_id": event.get("document_id"),
        "metadata": event.get("metadata", {}),
        "text_extraction": text_extraction,
        "llm": {
            "model": llm["model"],
            "response_id": llm["response_id"],
            "usage": llm["usage"],
            "usage_metrics": usage_metrics,
            "cache": llm.get("cache", {}),
            "chunking": llm.get("chunking", {}),
            "confidence": confidence,
            "prompt_safety": llm.get("prompt_safety", {}),
        },
        "extracted_data": extracted_data,
        "validation": event.get("validation", {}),
        "business_rules": event.get("business_rules", {}),
        "artifacts": artifacts,
    }
    status_payload = {
        "request_id": event["request_id"],
        "status": "SUCCEEDED",
        "submitted_at": event.get("submitted_at"),
        "document": event["document"],
        "document_format": document_format,
        "extraction_profile": event["extraction_profile"],
        "result_uri": s3_uri(output_bucket, result_key),
        "artifacts": artifacts,
    }

    put_json(output_bucket, result_key, result_payload)
    put_json(output_bucket, status_key, status_payload)

    log_json(
        logger,
        "Extraction result persisted",
        request_id=event["request_id"],
        result_uri=s3_uri(output_bucket, result_key),
    )

    # --- metrics ---
    gross_pay = totals.get("gross_pay") if totals else None
    net_pay = totals.get("net_pay") if totals else None
    pdf_strategy = text_extraction.get("strategy_used") if document_format == "pdf" else None

    emit_extraction_success(
        fmt=document_format,
        profile_id=event["extraction_profile"].get("id", "unknown"),
        duration_seconds=_duration_seconds(event.get("submitted_at")),
        cost_usd=usage_metrics.get("estimated_cost_usd"),
        input_tokens=int(usage_metrics.get("input_tokens") or 0),
        output_tokens=int(usage_metrics.get("output_tokens") or 0),
        confidence_score=confidence.get("score") if confidence else None,
        fields_null_count=_count_nulls(extracted_data),
        gross_pay=float(gross_pay) if isinstance(gross_pay, (int, float)) else None,
        net_pay=float(net_pay) if isinstance(net_pay, (int, float)) else None,
        pdf_strategy=pdf_strategy,
    )

    return event
