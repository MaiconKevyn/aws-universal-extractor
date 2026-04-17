from typing import Any

from app_common.logging import get_logger, log_json
from app_common.openai_client import OpenAIExtractionClient
from app_common.s3_utils import get_object_text, put_json
from app_common.validators import to_metadata_json


logger = get_logger(__name__)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    raw_text_location = event["artifacts"]["raw_text"]
    document_text = get_object_text(raw_text_location["bucket"], raw_text_location["key"])
    profile = event["resolved_profile"]
    client = OpenAIExtractionClient()

    extraction_context = {
        "client_id": event.get("client_id", ""),
        "document_id": event.get("document_id", ""),
        "metadata_json": to_metadata_json(event.get("metadata") or {}),
        "document_text": document_text,
    }
    llm_result = client.extract(profile=profile, document_text=document_text, context=extraction_context)

    llm_response_key = f"{event['artifacts']['output_prefix']}/llm_response.json"
    put_json(
        bucket=event["artifacts"]["output_bucket"],
        key=llm_response_key,
        payload={
            "request_id": event["request_id"],
            "response_id": llm_result["response_id"],
            "model": llm_result["model"],
            "usage": llm_result["usage"],
            "raw_output": llm_result["raw_output"],
        },
    )

    event["artifacts"]["llm_response"] = {
        "bucket": event["artifacts"]["output_bucket"],
        "key": llm_response_key,
    }
    event["llm_extraction"] = {
        "response_id": llm_result["response_id"],
        "model": llm_result["model"],
        "usage": llm_result["usage"],
        "data": llm_result["data"],
    }

    log_json(
        logger,
        "LLM extraction completed",
        request_id=event["request_id"],
        model=llm_result["model"],
        response_id=llm_result["response_id"],
    )
    return event

