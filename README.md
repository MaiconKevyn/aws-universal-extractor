# Universal Extractor

Pipeline assíncrona em AWS para extração estruturada de documentos usando Step Functions, Lambda, S3 e OpenAI.

## MVP

- Entrada via endpoint HTTP assíncrono
- Documento de entrada armazenado em S3
- Extração de texto por formato, começando com PDF via PyMuPDF e XLSX via OpenPyXL
- Perfil de extração versionado em YAML
- Fixtures separadas de execuções: `datasets/fixtures/...` para entradas de teste e `runs/...` para artefatos de processamento
- Saída persistida por execução em `runs/<profile>/<version>/<YYYY>/<MM>/<DD>/<request_id>/`

## Bucket de documentos

O bucket padrão criado pelo `template.yml` segue este padrão:

```text
payroll-<stage>-<account-id>-<region>
```

No ambiente `dev` atual, isso fica:

```text
payroll-dev-498504717701-sa-east-1
```

Observação: `Payroll/` não é um nome válido de bucket S3. Em S3, `Payroll/` seria um prefixo/pasta. Bucket precisa ser minúsculo, sem `/`, e globalmente único.

As fixtures de payroll ficam separadas por formato no prefixo:

```text
s3://<documents-bucket>/datasets/fixtures/payroll/pdf/
s3://<documents-bucket>/datasets/fixtures/payroll/xlsx/
```

O Jenkinsfile sincroniza automaticamente as fixtures locais de `tests/fixtures/payroll/` para esse prefixo após o deploy, quando `SYNC_PAYROLL_FIXTURES=true`.

As execuções geram artefatos em uma árvore separada:

```text
s3://<documents-bucket>/runs/payroll/v1/2026/04/18/req_<id>/
  input.json
  document_metadata.json
  raw_text.txt
  llm_response.json
  result.json
  status.json
  error.json
```

`error.json` só existe em execuções com falha. Essa separação mantém datasets, arquivos de entrada e resultados auditáveis sem misturar origem com processamento.

## Payload de entrada

```json
{
  "document": {
    "bucket": "payroll-dev-498504717701-sa-east-1",
    "key": "datasets/fixtures/payroll/pdf/paystub_001_canonical.pdf"
  },
  "extraction_profile": {
    "id": "payroll",
    "version": "v1"
  },
  "client_id": "internal",
  "document_id": "paystub_001_canonical",
  "idempotency_key": "internal-paystub-001-payroll-v1",
  "metadata": {
    "source_system": "jenkins_fixture"
  }
}
```

## Resposta do endpoint

```json
{
  "status": "accepted",
  "request_id": "req_123",
  "execution_arn": "arn:aws:states:sa-east-1:123456789012:execution:document-extraction:req_123",
  "message": "Extraction triggered successfully",
  "output_prefix": "s3://payroll-dev-498504717701-sa-east-1/runs/payroll/v1/2026/04/18/req_123"
}
```

## Estrutura do projeto

```text
template.yml
layers/
  common/
    python/
      app_common/
functions/
  submit_extraction/
  fetch_document/
  extract_pdf_text/
  extract_xlsx_text/
  load_extraction_profile/
  run_llm_extraction/
  validate_schema/
  persist_result/
  persist_failure/
profiles/
  cash_requirements/
    v1.yml
  payroll/
    v1.yml
events/
  submit-extraction.json
  submit-payroll-xlsx-extraction.json
tests/
  fixtures/
    payroll/
      pdf/
      xlsx/
```

## Perfil de extração

Cada perfil é versionado em um arquivo YAML, por exemplo `profiles/payroll/v1.yml`.

O arquivo concentra:

- metadados do perfil
- prompt base
- schema JSON esperado
- regras simples de validação

## Fluxo da State Machine

1. `SubmitExtraction` recebe a requisição e inicia a execution
2. `FetchDocument` valida que o documento existe no S3, detecta o formato e persiste `document_metadata.json`
3. `RouteByFormat` escolhe o extractor correto
4. `ExtractPdfText` ou `ExtractXlsxText` extrai texto e persiste `raw_text.txt`
5. `LoadExtractionProfile` carrega o YAML do perfil versionado
6. `RunLLMExtraction` chama a OpenAI com Structured Outputs
7. `ValidateSchema` valida o JSON retornado
8. `PersistResult` grava `result.json` e `status.json`
9. Em caso de erro, `PersistFailure` grava `error.json` e `status.json`

## Deploy

O `template.yml` foi estruturado para deploy via AWS SAM.

Comandos esperados:

```bash
sam build
sam deploy --guided
```

Parâmetros relevantes:

- `StageName`: ambiente, por exemplo `dev`
- `DocumentsBucketName`: opcional; se vazio, usa `payroll-<stage>-<account-id>-<region>`
- `OpenAIApiKeySecretArn`: ARN do secret da OpenAI no Secrets Manager
- `OpenAIModel`: modelo usado na extração

## Variáveis de ambiente esperadas

- `DOCUMENTS_BUCKET_NAME`
- `OPENAI_API_KEY_SECRET_ARN`
- `OPENAI_API_KEY` para desenvolvimento local via `.env`
- `OPENAI_MODEL`
- `STATE_MACHINE_ARN`
- `PROFILES_ROOT` opcional
