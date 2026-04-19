# Production Readiness Checkpoints

This document tracks the Priority 1 AI Engineering gaps and the concrete checkpoints implemented in this repository.

## 1.1 OCR Fallback

Status: implemented.

Checkpoints:
- Classify PDFs before extraction: encrypted, corrupted, scanned, sparse, native text.
- Use text-layer Markdown for native PDFs.
- Route scanned PDFs to AWS Textract synchronous OCR/table extraction.
- Keep OpenAI Vision as an explicit fallback switch for cases where Textract is unavailable or insufficient.
- Persist `pdf_extraction` metadata with classification, strategy used, fallback chain, and per-page details.

## 1.2 Evaluation Harness In CI

Status: implemented.

Checkpoints:
- Add deterministic offline fixture evaluation for every PR.
- Validate expected JSON files against the active profile schema.
- Validate local text normalization for supported fixture formats.
- Run optional LLM field-level evaluation when `OPENAI_API_KEY` is configured in GitHub Actions.
- Upload JSON evaluation reports as CI artifacts.

Implementation:
- `.github/workflows/ci.yml`
- `scripts/evaluate_fixtures.py`

## 1.3 Cost And Token Tracking

Status: implemented.

Checkpoints:
- Normalize OpenAI usage into input, cached input, output, and total token counts.
- Estimate per-run cost using model pricing metadata.
- Persist `usage_metrics.json` for each run.
- Include usage and cost metrics inside `llm_response.json` and `result.json`.
- Mark cache hits as zero marginal model cost.

Implementation:
- `layers/common/python/app_common/usage.py`
- `functions/run_llm_extraction/app.py`

## 1.4 Retry And Error Taxonomy

Status: implemented.

Checkpoints:
- Classify OpenAI 429, timeout, connection, and 5xx failures as retryable.
- Classify auth, permission, and bad request failures as non-retryable.
- Surface typed Lambda errors to Step Functions.
- Retry only retryable LLM errors and Lambda service failures with exponential backoff and jitter.

Implementation:
- `layers/common/python/app_common/llm_errors.py`
- `layers/common/python/app_common/openai_client.py`
- `template.yml`

## 1.5 Prompt Injection Defense

Status: implemented.

Checkpoints:
- Treat document text as untrusted source data.
- Wrap document text in explicit untrusted-data boundaries before prompt rendering.
- Add profile-level system prompt instruction to ignore instructions inside documents.
- Detect common prompt injection patterns and persist `prompt_safety` metadata.
- Keep suspicious snippets out of logs; store only bounded snippets in the run artifact.

Implementation:
- `layers/common/python/app_common/prompt_safety.py`
- `functions/run_llm_extraction/app.py`
- `profiles/*/v1.yml`

## 1.6 Long Document Chunking

Status: implemented as bounded map/merge chunking.

Checkpoints:
- Estimate token volume from normalized document text.
- Use single-call extraction under `MAX_SINGLE_PROMPT_CHARS`.
- Split oversized documents into bounded chunks when `ENABLE_LLM_CHUNKING=true`.
- Enforce `MAX_LLM_CHUNKS` to prevent uncontrolled cost.
- Merge chunk-level structured outputs with deterministic recursive merge semantics.
- Raise `DocumentTooLargeError` when the document exceeds configured limits.

Implementation:
- `layers/common/python/app_common/chunking.py`
- `functions/run_llm_extraction/app.py`

## 1.7 Confidence And Abstain

Status: implemented as deterministic confidence scoring with optional gate.

Checkpoints:
- Score completeness across required schema fields.
- Score simple evidence alignment against source text for scalar fields.
- Persist confidence report with score, threshold, missing fields, and evidence hit counts.
- Support optional `ENABLE_CONFIDENCE_GATE=true` to fail low-confidence outputs before persistence.

Implementation:
- `layers/common/python/app_common/confidence.py`
- `functions/run_llm_extraction/app.py`
- `functions/validate_schema/app.py`

## 1.8 LLM-Native Observability

Status: implemented as portable run-level LLM trace artifacts.

Checkpoints:
- Capture LLM spans for input load, prompt safety, cache lookup, model extraction, and cache store.
- Persist `llm_trace.json` per run.
- Attach usage, cache, chunking, confidence, and prompt-safety metadata to LLM response artifacts.
- Keep the design vendor-neutral so Langfuse/LangSmith/Honeycomb export can be added without changing the pipeline contract.

Implementation:
- `layers/common/python/app_common/observability.py`
- `functions/run_llm_extraction/app.py`

## 1.9 Caching And Deduplication

Status: implemented.

Checkpoints:
- Hash document text, profile prompt/schema/validation, and model ID into a stable cache key.
- Store successful LLM results in DynamoDB with TTL.
- Reuse cached responses for same document + same profile + same model + same prompt/schema.
- Persist cache metadata in `llm_response.json`, `usage_metrics.json`, and `result.json`.
- Skip DynamoDB writes when cached payloads exceed safe item size.

Implementation:
- `layers/common/python/app_common/cache.py`
- `functions/run_llm_extraction/app.py`
- `template.yml`
