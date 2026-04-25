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
- `metrics.py` — fire-and-forget CloudWatch metrics module; never raises. Emits two series per metric: `Stage+Format+Profile` dimensions (detailed dashboards) and `Stage`-only aggregate (alarms and overview panels). Three public functions: `emit_extraction_success`, `emit_extraction_failure`, `emit_business_rules`.

### State machine flow (`template.yml`)

`SubmitExtraction` (API, `POST /extractions`) → start execution → `FetchDocument` → `RouteByFormat` → `ExtractPdfText`, `ExtractXlsxText`, `ExtractCsvText`, or `ExtractDocxText` → `LoadExtractionProfile` → `RunLlmExtraction` → `ValidateSchema` → `ValidateBusinessRules` → `PersistResult`. Every task has a `Catch: States.ALL → PersistFailure` with `ResultPath: $.error`. The state input is augmented by `SubmitExtraction` with `request_id`, `submitted_at`, and `artifacts.{input_document_uri, output_bucket, output_prefix, run_uri, input}`; each downstream step mutates and forwards this object, appending `artifacts.document_metadata`, `artifacts.raw_text`, `resolved_profile`, `llm_extraction`, `validation`, `business_rules`, etc.

`GetExtractionStatus` (API, `GET /extractions/{request_id}`) reconstructs the execution ARN from `request_id` (the execution name is the sanitized `request_id`), calls `DescribeExecution`, and returns the richer `status.json` or `error.json` from S3 once the execution finishes. Returns 202 while RUNNING, 200 on terminal states, 404 if the execution does not exist.

### Business rules validation (`functions/validate_business_rules/`)

Runs after `ValidateSchema` (JSON structure check) and before `PersistResult`. Checks 7 payroll invariants that JSON Schema cannot express: `gross_pay > 0`, `net_pay > 0`, `gross >= net`, math check `|gross - deductions - net| / gross < 2%`, `employer.name` present, `employee.name` present, `pay_period` dates present. Violations are **recorded, not fatal** — the pipeline always reaches `PersistResult`, and `result.json` includes `business_rules.{passed, score, violations, rules_checked}`.

### PDF multi-strategy extraction (`functions/extract_pdf_text/`)

`ExtractPdfText` is a multi-strategy pipeline with automatic fallback:

1. **Classify** (`classifier.py`) — inspects the PDF before choosing a strategy. Detects: `is_scanned` (avg < 50 chars/page), `is_sparse` (avg < 200 chars/page), `is_encrypted`, `is_corrupted`, `has_tables`.

2. **Strategy chain** (`app.py:_choose_strategy_chain`) — picks strategies based on classification and env toggles:
   - Scanned PDF → `[textract, vision]` (skips text layer entirely)
   - Normal/sparse PDF → `[text_layer, textract, vision]`
   - Each strategy is tried in order; on `StrategyError` the next one runs.

3. **Strategies** (`strategies.py`):
   - `text_layer` — PyMuPDF + pymupdf4llm → Markdown. Always attempted first for non-scanned PDFs.
   - `textract` — renders each page to PNG at 220 DPI → `AnalyzeDocument` (TABLES + FORMS). On by default (`ENABLE_TEXTRACT=true`). **Textract is not available in `sa-east-1`** — set `TEXTRACT_REGION` to a supported region (e.g. `us-east-1`). Currently uses sync per-page calls; async (`StartDocumentAnalysis` + SNS) is the right pattern for documents > 20 pages.
   - `vision` — renders each page to PNG → OpenAI vision model (`OPENAI_VISION_MODEL`, default `gpt-4o`) transcribes to Markdown. Off by default (`ENABLE_VISION_FALLBACK=false`).

4. **Output** — concatenated Markdown with page headers (`=== Page N (method) ===`); rich `pdf_extraction` metadata attached to the event for observability.

### Extraction profiles

Versioned YAML at `profiles/<id>/<version>.yml` (e.g. `profiles/cash_requirements/v1.yml`). Each profile bundles the system/user prompt templates, the JSON Schema passed directly to Structured Outputs, and validation rules. Adding a new profile means adding a YAML file — no code change needed. The submission payload references a profile by `extraction_profile.id` + `version`.

## Deployment

- Jenkins pipeline (`Jenkinsfile`) runs Checkout → Preflight (needs `python3.13`) → Prepare Python (builds `.aws-sam/runtime-deps`) → Resolve AWS Identity → `sam validate` → `sam build` → Deploy → Sync Payroll Fixtures → **Deploy UI**. Deploy requires `OPENAI_API_KEY_SECRET_ARN` (must match `arn:aws:secretsmanager:*`) and uses `--resolve-s3` unless `SAM_S3_BUCKET` is set. The Deploy UI stage reads the `UiBucketName` CloudFormation output and uploads `ui/index.html` with `Content-Type: text/html`.
- A local Jenkins setup lives under `universal-extractor-jenkins/` (gitignored).
- After deploy, CloudFormation outputs include `UiUrl` (CloudFront HTTPS URL for the SPA), `ExtractionDashboardUrl` (CloudWatch dashboard direct link), and `ExtractionAlertsTopicArn` (SNS topic for alarm notifications — subscribe an email via the console).

## Environment variables

Required at runtime: `DOCUMENTS_BUCKET_NAME`, `OPENAI_API_KEY_SECRET_ARN` (or `OPENAI_API_KEY` for local dev via `.env`), `OPENAI_MODEL`, `STATE_MACHINE_ARN` (set on `SubmitExtractionFunction` and `GetExtractionStatusFunction`). Optional: `PROFILES_ROOT`, `OPENAI_BASE_URL`, `STAGE_NAME`.

PDF extraction toggles: `ENABLE_TEXTRACT` (default `true`), `ENABLE_VISION_FALLBACK` (default `false`), `TEXTRACT_REGION` (required if deploying to a region without Textract, e.g. `sa-east-1`), `OPENAI_VISION_MODEL` (default `gpt-4o`).
