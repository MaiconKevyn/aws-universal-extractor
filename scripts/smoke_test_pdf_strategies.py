"""Compare PDF extraction strategies end-to-end against ground truth.

Runs each available strategy (text_layer, textract, vision) on a set of PDF
fixtures and reports per-strategy accuracy vs. the paired .expected.json file.
Purpose: verify that the multi-strategy extractor preserves accuracy on
native-text PDFs and gains coverage on scanned PDFs.

Usage:
    ./.venv/bin/python scripts/smoke_test_pdf_strategies.py \
        --fixture tests/fixtures/payroll/pdf/paystub_001_canonical.pdf \
        --fixture tests/fixtures/payroll/pdf/paystub_006_scanned.pdf \
        --strategies text_layer,textract

Environment:
    TEXTRACT_REGION       — region with Textract endpoint (e.g. us-east-1)
    OPENAI_API_KEY        — required for accuracy scoring + vision strategy
    OPENAI_VISION_MODEL   — default gpt-4o
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "layers" / "common" / "python"))
sys.path.insert(0, str(REPO_ROOT))

from app_common.openai_client import OpenAIExtractionClient  # noqa: E402
from app_common.profiles import load_profile  # noqa: E402
from app_common.validators import to_metadata_json  # noqa: E402
from functions.extract_pdf_text.classifier import classify  # noqa: E402
from functions.extract_pdf_text.strategies import (  # noqa: E402
    StrategyError,
    extract_text_layer,
    extract_via_textract,
    extract_via_vision,
)


STRATEGIES = {
    "text_layer": extract_text_layer,
    "textract": extract_via_textract,
    "vision": extract_via_vision,
}


@dataclass
class Result:
    fixture: str
    strategy: str
    success: bool
    accuracy: float | None
    char_count: int | None
    elapsed_s: float
    error: str | None


def _flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _match(a, b) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-3, abs_tol=0.01)
    return str(a).strip() == str(b).strip()


def _accuracy(predicted: dict, expected: dict) -> float:
    p = _flatten(predicted)
    e = _flatten(expected)
    keys = sorted(set(p) | set(e))
    if not keys:
        return 1.0
    hits = sum(1 for k in keys if _match(p.get(k), e.get(k)))
    return hits / len(keys)


def run(fixture: Path, strategy: str, profile: dict, llm: OpenAIExtractionClient) -> Result:
    fn = STRATEGIES[strategy]
    pdf_bytes = fixture.read_bytes()
    start = time.monotonic()
    try:
        pages = fn(pdf_bytes)
        document_text = "\n\n".join(
            f"=== Page {p.page_number} ({p.method}) ===\n{p.markdown}" for p in pages
        )
        gt_path = fixture.with_name(fixture.stem + ".expected.json")
        expected = json.loads(gt_path.read_text(encoding="utf-8"))
        ctx = {
            "client_id": "smoke",
            "document_id": fixture.stem,
            "metadata_json": to_metadata_json({}),
            "document_text": document_text,
        }
        result = llm.extract(profile=profile, document_text=document_text, context=ctx)
        acc = _accuracy(result["data"], expected)
        return Result(
            fixture=fixture.name,
            strategy=strategy,
            success=True,
            accuracy=acc,
            char_count=len(document_text),
            elapsed_s=time.monotonic() - start,
            error=None,
        )
    except StrategyError as exc:
        return Result(
            fixture=fixture.name,
            strategy=strategy,
            success=False,
            accuracy=None,
            char_count=None,
            elapsed_s=time.monotonic() - start,
            error=f"StrategyError: {exc}",
        )
    except Exception as exc:
        return Result(
            fixture=fixture.name,
            strategy=strategy,
            success=False,
            accuracy=None,
            char_count=None,
            elapsed_s=time.monotonic() - start,
            error=f"{type(exc).__name__}: {exc}",
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="append", type=Path, required=True)
    ap.add_argument(
        "--strategies",
        default="text_layer,textract",
        help="Comma-separated subset of: text_layer, textract, vision",
    )
    args = ap.parse_args()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    for s in strategies:
        if s not in STRATEGIES:
            raise SystemExit(f"Unknown strategy: {s}. Available: {list(STRATEGIES)}")

    profile = load_profile(str(REPO_ROOT / "profiles"), "payroll", "v1")
    llm = OpenAIExtractionClient()

    print(f"{'Fixture':<40}  {'Strategy':<12}  {'Class':<10}  {'Acc':>6}  {'Chars':>6}  {'Time':>6}  Notes")
    print("-" * 110)

    for fixture in args.fixture:
        pdf_bytes = fixture.read_bytes()
        cls = classify(pdf_bytes)
        class_label = "scanned" if cls.is_scanned else ("sparse" if cls.is_sparse else "native")
        for strategy in strategies:
            r = run(fixture, strategy, profile, llm)
            acc_s = f"{r.accuracy*100:5.1f}%" if r.accuracy is not None else "   --"
            chars_s = f"{r.char_count}" if r.char_count else "--"
            note = "" if r.success else r.error
            print(
                f"{r.fixture:<40}  {r.strategy:<12}  {class_label:<10}  {acc_s:>6}  {chars_s:>6}  {r.elapsed_s:5.1f}s  {note}"
            )


if __name__ == "__main__":
    main()
