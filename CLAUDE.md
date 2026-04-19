# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Async multi-format document extraction pipeline on AWS (SAM + Step Functions + Lambda + S3 + OpenAI). A client POSTs a document reference to an API Gateway endpoint; `SubmitExtraction` starts a Standard Step Functions execution that fetches the document, routes by format, extracts raw text, loads a versioned YAML extraction profile, calls the OpenAI Responses API with Structured Outputs, validates the JSON against the profile's schema, and persists run artifacts back to the same S3 bucket. Runtime is Python 3.13.

## Common commands

Environment setup (mirrors the Jenkins `Prepare Python` stage):

```bash
python3.13 -m venv .venv
./.venv/bin/pip install -r requirements.txt awscli aws-sam-cli
```

SAM build/deploy (relies on the `makefile` BuildMethod, see below):

```bash
# Runtime deps must be prebuilt into .aws-sam/runtime-deps before `sam build`
rm -rf .aws-sam/runtime-deps
mkdir -p .aws-sam/runtime-deps
./.venv/bin/pip install -r requirements.txt -t .aws-sam/runtime-deps --upgrade --no-compile

./.venv/bin/sam validate --template-file template.yml --region sa-east-1
./.venv/bin/sam build --template-file template.yml
./.venv/bin/sam deploy --guided   # first time; afterwards use samconfig or the Jenkins params
```

There are no automated tests wired up. `tests/fixtures/` contains local fixture documents and expected JSON outputs used for manual/API smoke testing. There is no lint config.

Sample API event for local invocation lives at `events/submit-extraction.json`.

## Architecture

### Build model (important, non-obvious)

Every Lambda uses `BuildMethod: makefile` and shares `CodeUri: .` at the repo root. The `Makefile` has one target per function, all delegating to the same `build_lambda` recipe that copies `functions/`, `profiles/`, and the contents of `$(PROJECT_ROOT)/.aws-sam/runtime-deps` into each function's artifact dir. Consequences:

- Dependencies are **not** installed by `sam build`. You must `pip install -r requirements.txt -t .aws-sam/runtime-deps` first (the Jenkinsfile does this). If `runtime-deps` is missing, every function build fails the `test -d` guard.
- All handlers ship with the full codebase and profile catalog baked in — the Lambda task root contains `functions/`, `profiles/`, and third-party packages side-by-side.
- Handlers are referenced as `functions.<name>.app.lambda_handler` (dotted import), so `functions/__init__.py` must stay in place.

### Shared layer

`layers/common/python/app_common/` is published as `CommonLayer` and imported as `from app_common import ...` in every function. Key modules:

- `config.py` — `get_settings()` returns a frozen `Settings` from env vars; `load_dotenv()` runs at import time so local dev reads `.env`. `default_profiles_root()` picks `PROFILES_ROOT` > `$LAMBDA_TASK_ROOT/profiles` > `cwd/profiles`. `load_secret()` pulls `OPENAI_API_KEY` from Secrets Manager, accepting either a plain string or a JSON object with keys `OPENAI_API_KEY` / `api_key` / `openai_api_key`.
- `s3_utils.py` — module-level `boto3.client("s3")` (imported at cold start). `derive_output_prefix` computes `runs/<profile_id>/<version>/<YYYY>/<MM>/<DD>/<request_id>/`, keeping run artifacts separate from source datasets.
- `profiles.py` — loads `profiles/<id>/<version>.yml` and enforces required keys (`id, version, prompt, schema, validation`), `prompt.system` + `prompt.user_template`, and `schema.type == "object"` with `additionalProperties: false` at the root.
- `openai_client.py` — wraps the OpenAI **Responses API** with `text.format = json_schema` (Structured Outputs). Renders `{{var}}` placeholders in `prompt.user_template`. `strict` defaults to `profile.validation.strict_schema` (default true).
- `validators.py` — `validate_submission_payload` gates the API handler; `to_metadata_json` prepares metadata for prompt injection.
- `exceptions.py` — domain errors (`RequestValidationError`, `ProfileNotFoundError`, `ProfileValidationError`, `DocumentExtractionError`, etc.).

### State machine flow (`template.yml`)

`SubmitExtraction` (API, POST /extractions) → start execution → `FetchDocument` → `RouteByFormat` → `ExtractPdfText`, `ExtractXlsxText`, `ExtractCsvText`, or `ExtractDocxText` → `LoadExtractionProfile` → `RunLlmExtraction` → `ValidateSchema` → `PersistResult`. Every task has a `Catch: States.ALL → PersistFailure` with `ResultPath: $.error`. The state input is augmented by `SubmitExtraction` with `request_id`, `submitted_at`, and `artifacts.{input_document_uri, output_bucket, output_prefix, run_uri, input}`; each downstream step mutates and forwards this object, appending `artifacts.document_metadata`, `artifacts.raw_text`, `resolved_profile`, `llm_extraction`, etc. PyMuPDF raises `DocumentExtractionError` on scanned PDFs — there is no OCR fallback yet.

### Extraction profiles

Versioned YAML at `profiles/<id>/<version>.yml` (e.g. `profiles/cash_requirements/v1.yml`). Each profile bundles the system/user prompt templates, the JSON Schema passed directly to Structured Outputs, and validation rules. Adding a new profile means adding a YAML file — no code change needed. The submission payload references a profile by `extraction_profile.id` + `version`.

## Deployment

- Jenkins pipeline (`Jenkinsfile`) runs Checkout → Preflight (needs `python3.13`) → Prepare Python (builds `.aws-sam/runtime-deps`) → Resolve AWS Identity → `sam validate` → `sam build` → Deploy → optional fixture sync. Deploy requires `OPENAI_API_KEY_SECRET_ARN` (must match `arn:aws:secretsmanager:*`) and uses `--resolve-s3` unless `SAM_S3_BUCKET` is set. Fixture sync uploads local `tests/fixtures/payroll/{pdf,xlsx,csv,docx}` into `datasets/fixtures/payroll/{pdf,xlsx,csv,docx}` in the deployed documents bucket.
- A local Jenkins setup lives under `universal-extractor-jenkins/` (gitignored).

## Environment variables

Required at runtime: `DOCUMENTS_BUCKET_NAME`, `OPENAI_API_KEY_SECRET_ARN` (or `OPENAI_API_KEY` for local dev via `.env`), `OPENAI_MODEL`, `STATE_MACHINE_ARN`. Optional: `PROFILES_ROOT`, `OPENAI_BASE_URL`, `STAGE_NAME`.
