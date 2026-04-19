from decimal import Decimal
from typing import Any


DEFAULT_PRICING_PER_1M_TOKENS: dict[str, dict[str, Decimal]] = {
    "gpt-4.1-mini": {
        "input": Decimal("0.40"),
        "cached_input": Decimal("0.10"),
        "output": Decimal("1.60"),
    },
    "gpt-4.1": {
        "input": Decimal("2.00"),
        "cached_input": Decimal("0.50"),
        "output": Decimal("8.00"),
    },
    "gpt-4.1-nano": {
        "input": Decimal("0.10"),
        "cached_input": Decimal("0.025"),
        "output": Decimal("0.40"),
    },
}


def normalize_usage(usage: dict[str, Any] | None) -> dict[str, int]:
    usage = usage or {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    cached_input_tokens = 0

    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    if isinstance(details, dict):
        cached_input_tokens = int(details.get("cached_tokens") or details.get("cached_input_tokens") or 0)

    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens)
    billable_input_tokens = max(0, input_tokens - cached_input_tokens)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "billable_input_tokens": billable_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def aggregate_usage(usages: list[dict[str, Any]]) -> dict[str, int]:
    total = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "billable_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    for usage in usages:
        normalized = normalize_usage(usage)
        for key in total:
            total[key] += normalized[key]
    return total


def build_usage_metrics(
    *,
    model: str,
    usage: dict[str, Any] | None,
    cache_hit: bool = False,
) -> dict[str, Any]:
    normalized = normalize_usage(usage)
    pricing = DEFAULT_PRICING_PER_1M_TOKENS.get(model)
    estimated_cost_usd = None

    if cache_hit:
        estimated_cost_usd = 0.0
    elif pricing:
        estimated_cost_usd = float(
            (
                Decimal(normalized["billable_input_tokens"]) * pricing["input"]
                + Decimal(normalized["cached_input_tokens"]) * pricing["cached_input"]
                + Decimal(normalized["output_tokens"]) * pricing["output"]
            )
            / Decimal(1_000_000)
        )

    return {
        **normalized,
        "model": model,
        "cache_hit": cache_hit,
        "estimated_cost_usd": estimated_cost_usd,
        "pricing": (
            {
                "unit": "USD per 1M tokens",
                "input": float(pricing["input"]),
                "cached_input": float(pricing["cached_input"]),
                "output": float(pricing["output"]),
            }
            if pricing
            else None
        ),
    }
