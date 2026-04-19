"""Run the extraction pipeline locally against a PDF on disk.

Mirrors the Lambda flow (ExtractPdfText -> LoadExtractionProfile -> RunLlmExtraction
-> ValidateSchema) but reads from the filesystem instead of S3 so you can iterate on
prompts / schemas without deploying.

Uses the exact same modules that run inside the Lambdas (layers/common/python/app_common).

Usage:
    ./.venv/bin/python scripts/extract_locally.py \
        --pdf tests/fixtures/payroll/pdf/paystub_001_canonical.pdf \
        --profile payroll --version v1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import fitz
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "layers" / "common" / "python"))

from app_common.openai_client import OpenAIExtractionClient  # noqa: E402
from app_common.profiles import load_profile  # noqa: E402
from app_common.validators import to_metadata_json  # noqa: E402


def extract_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    pages = [page.get_text("text").strip() for page in doc]
    return "\n\n".join(p for p in pages if p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument(
        "--profiles-root",
        type=Path,
        default=REPO_ROOT / "profiles",
    )
    ap.add_argument("--client-id", default="local")
    ap.add_argument("--document-id", default="local-doc")
    args = ap.parse_args()

    if not args.pdf.exists():
        raise SystemExit(f"PDF not found: {args.pdf}")

    print(f"[1/4] Extracting text from {args.pdf.name}")
    document_text = extract_text(args.pdf)
    if not document_text.strip():
        raise SystemExit("No extractable text — PDF is likely scanned.")
    print(f"      {len(document_text)} chars extracted")

    print(f"[2/4] Loading profile {args.profile}/{args.version}")
    profile = load_profile(str(args.profiles_root), args.profile, args.version)

    print(f"[3/4] Calling OpenAI (model from OPENAI_MODEL env)")
    client = OpenAIExtractionClient()
    context = {
        "client_id": args.client_id,
        "document_id": args.document_id,
        "metadata_json": to_metadata_json({}),
        "document_text": document_text,
    }
    result = client.extract(profile=profile, document_text=document_text, context=context)

    print(f"[4/4] Validating against profile schema")
    validator = Draft202012Validator(profile["schema"])
    errors = sorted(validator.iter_errors(result["data"]), key=lambda e: e.path)
    if errors:
        print(f"      {len(errors)} schema error(s):")
        for err in errors:
            path = ".".join(str(p) for p in err.path) or "<root>"
            print(f"        - {path}: {err.message}")
    else:
        print("      OK — schema valid")

    print("\n--- extracted JSON ---")
    print(json.dumps(result["data"], indent=2, ensure_ascii=False))
    print("\n--- usage ---")
    print(json.dumps({
        "model": result["model"],
        "response_id": result["response_id"],
        "usage": result["usage"],
    }, indent=2))


if __name__ == "__main__":
    main()
