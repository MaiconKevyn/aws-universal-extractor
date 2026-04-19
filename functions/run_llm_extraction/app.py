import json
import os
from time import perf_counter
from typing import Any

from app_common.cache import ExtractionCache, build_extraction_cache_key, document_hash, truthy
from app_common.chunking import approximate_token_count, chunk_text, merge_extraction_outputs
from app_common.confidence import score_extraction_confidence
from app_common.llm_errors import DocumentTooLargeError
from app_common.logging import get_logger, log_json
from app_common.observability import TraceRecorder
from app_common.openai_client import OpenAIExtractionClient
from app_common.prompt_safety import assess_prompt_injection_risk, wrap_untrusted_document_text
from app_common.s3_utils import get_object_text, put_json
from app_common.usage import aggregate_usage, build_usage_metrics
from app_common.validators import to_metadata_json


logger = get_logger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _base_context(event: dict[str, Any]) -> dict[str, str]:
    return {
        "client_id": event.get("client_id", ""),
        "document_id": event.get("document_id", ""),
        "metadata_json": to_metadata_json(event.get("metadata") or {}),
    }


def _extract_single(
    *,
    client: OpenAIExtractionClient,
    profile: dict[str, Any],
    document_text: str,
    context: dict[str, str],
) -> dict[str, Any]:
    return client.extract(
        profile=profile,
        document_text=document_text,
        context={
            **context,
            "document_text": wrap_untrusted_document_text(document_text),
        },
    )


def _extract_with_optional_chunking(
    *,
    client: OpenAIExtractionClient,
    profile: dict[str, Any],
    document_text: str,
    context: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    max_single_prompt_chars = _int_env("MAX_SINGLE_PROMPT_CHARS", 120_000)
    chunk_chars = _int_env("LLM_CHUNK_CHARS", max_single_prompt_chars)
    max_chunks = _int_env("MAX_LLM_CHUNKS", 8)
    enable_chunking = truthy(os.getenv("ENABLE_LLM_CHUNKING"), default=True)

    metadata = {
        "enabled": enable_chunking,
        "input_chars": len(document_text),
        "estimated_input_tokens": approximate_token_count(document_text),
        "max_single_prompt_chars": max_single_prompt_chars,
        "chunk_chars": chunk_chars,
        "max_chunks": max_chunks,
        "used": False,
        "chunk_count": 1,
    }

    if len(document_text) <= max_single_prompt_chars:
        return _extract_single(
            client=client,
            profile=profile,
            document_text=document_text,
            context=context,
        ), metadata

    if not enable_chunking:
        raise DocumentTooLargeError(
            f"Document text has {len(document_text)} chars, above MAX_SINGLE_PROMPT_CHARS={max_single_prompt_chars}"
        )

    chunks = chunk_text(document_text, max_chars=chunk_chars)
    if len(chunks) > max_chunks:
        raise DocumentTooLargeError(
            f"Document requires {len(chunks)} chunks, above MAX_LLM_CHUNKS={max_chunks}"
        )

    chunk_results: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_header = (
            f"Document chunk {index} of {len(chunks)}. Extract fields present in this chunk only. "
            "Leave fields null when absent from this chunk.\n\n"
        )
        result = _extract_single(
            client=client,
            profile=profile,
            document_text=chunk_header + chunk,
            context=context,
        )
        chunk_results.append(result)

    merged_data = merge_extraction_outputs([r["data"] for r in chunk_results])
    usage = aggregate_usage([r.get("usage", {}) for r in chunk_results])
    metadata.update(
        {
            "used": True,
            "chunk_count": len(chunks),
            "chunk_sizes": [len(c) for c in chunks],
            "response_ids": [r["response_id"] for r in chunk_results],
        }
    )
    return {
        "response_id": "chunked:" + ",".join(r["response_id"] for r in chunk_results),
        "model": chunk_results[-1]["model"],
        "usage": usage,
        "data": merged_data,
        "raw_output": json.dumps(merged_data, ensure_ascii=True),
        "chunks": [
            {
                "index": index,
                "response_id": result["response_id"],
                "usage": result.get("usage", {}),
            }
            for index, result in enumerate(chunk_results, start=1)
        ],
    }, metadata


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    trace = TraceRecorder(request_id=event["request_id"])

    span = perf_counter()
    raw_text_location = event["artifacts"]["raw_text"]
    document_text = get_object_text(raw_text_location["bucket"], raw_text_location["key"])
    profile = event["resolved_profile"]
    client = OpenAIExtractionClient()
    trace.record(
        "load_input",
        span,
        {
            "document_chars": len(document_text),
            "estimated_input_tokens": approximate_token_count(document_text),
        },
    )

    span = perf_counter()
    prompt_safety = assess_prompt_injection_risk(document_text).to_dict()
    trace.record("prompt_safety", span, {"risk_score": prompt_safety["risk_score"], "flags": prompt_safety["flags"]})

    cache = ExtractionCache()
    doc_hash = document_hash(document_text)
    cache_key = build_extraction_cache_key(
        document_text=document_text,
        profile=profile,
        model=client.model,
    )
    cache_metadata = {
        "enabled": cache.enabled,
        "cache_key": cache_key,
        "document_sha256": doc_hash,
        "hit": False,
    }

    span = perf_counter()
    cached = cache.get(cache_key)
    trace.record("cache_lookup", span, {"enabled": cache.enabled, "hit": bool(cached)})

    if cached:
        llm_result = cached["llm_result"]
        chunking = llm_result.get("chunking", {"used": False, "chunk_count": 1})
        cache_metadata.update({"hit": True, "created_at": cached.get("created_at")})
    else:
        span = perf_counter()
        llm_result, chunking = _extract_with_optional_chunking(
            client=client,
            profile=profile,
            document_text=document_text,
            context=_base_context(event),
        )
        trace.record(
            "openai_extract",
            span,
            {
                "model": llm_result["model"],
                "chunk_count": chunking["chunk_count"],
                "chunking_used": chunking["used"],
            },
        )
        llm_result["chunking"] = chunking

        span = perf_counter()
        cache.put(
            cache_key=cache_key,
            document_sha256=doc_hash,
            profile=profile,
            model=llm_result["model"],
            llm_result=llm_result,
        )
        trace.record("cache_store", span, {"enabled": cache.enabled})

    usage_metrics = build_usage_metrics(
        model=llm_result["model"],
        usage=llm_result.get("usage", {}),
        cache_hit=cache_metadata["hit"],
    )
    confidence = score_extraction_confidence(
        extracted_data=llm_result["data"],
        schema=profile["schema"],
        validation_rules=profile["validation"],
        document_text=document_text,
    ).to_dict()

    llm_response_key = f"{event['artifacts']['output_prefix']}/llm_response.json"
    usage_metrics_key = f"{event['artifacts']['output_prefix']}/usage_metrics.json"
    trace_key = f"{event['artifacts']['output_prefix']}/llm_trace.json"

    response_payload = {
        "request_id": event["request_id"],
        "response_id": llm_result["response_id"],
        "model": llm_result["model"],
        "usage": llm_result.get("usage", {}),
        "usage_metrics": usage_metrics,
        "cache": cache_metadata,
        "chunking": chunking,
        "confidence": confidence,
        "prompt_safety": prompt_safety,
        "raw_output": llm_result["raw_output"],
        "chunks": llm_result.get("chunks", []),
    }
    put_json(bucket=event["artifacts"]["output_bucket"], key=llm_response_key, payload=response_payload)
    put_json(
        bucket=event["artifacts"]["output_bucket"],
        key=usage_metrics_key,
        payload={
            "request_id": event["request_id"],
            "usage_metrics": usage_metrics,
            "cache": cache_metadata,
        },
    )
    put_json(bucket=event["artifacts"]["output_bucket"], key=trace_key, payload=trace.to_dict())

    event["artifacts"]["llm_response"] = {
        "bucket": event["artifacts"]["output_bucket"],
        "key": llm_response_key,
    }
    event["artifacts"]["usage_metrics"] = {
        "bucket": event["artifacts"]["output_bucket"],
        "key": usage_metrics_key,
    }
    event["artifacts"]["llm_trace"] = {
        "bucket": event["artifacts"]["output_bucket"],
        "key": trace_key,
    }
    event["llm_extraction"] = {
        "response_id": llm_result["response_id"],
        "model": llm_result["model"],
        "usage": llm_result.get("usage", {}),
        "usage_metrics": usage_metrics,
        "data": llm_result["data"],
        "cache": cache_metadata,
        "chunking": chunking,
        "confidence": confidence,
        "prompt_safety": prompt_safety,
    }

    log_json(
        logger,
        "LLM extraction completed",
        request_id=event["request_id"],
        model=llm_result["model"],
        response_id=llm_result["response_id"],
        cache_hit=cache_metadata["hit"],
        confidence_score=confidence["score"],
        estimated_cost_usd=usage_metrics["estimated_cost_usd"],
    )
    return event
