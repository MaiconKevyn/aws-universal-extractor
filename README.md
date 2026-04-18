# Universal Extractor

Pipeline assíncrona em AWS para extração estruturada de documentos usando Step Functions, Lambda, S3 e OpenAI.

## MVP

- Entrada via endpoint HTTP assíncrono
- Documento de entrada armazenado em S3
- Extração de texto de PDF com PyMuPDF
- Perfil de extração versionado em YAML
- Saída persistida no mesmo diretório do documento em `extract/<profile>/<version>/<request_id>/`

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

Os PDFs de payroll usados como fixture ficam no prefixo:

```text
s3://<documents-bucket>/tests/fixtures/payrolls/
```

O Jenkinsfile sincroniza automaticamente os PDFs locais de `tests/fixtures/payrolls/*.pdf` para esse prefixo após o deploy, quando `SYNC_PAYROLL_FIXTURES=true`.

## Payload de entrada

```json
{
  "document": {
    "bucket": "payroll-dev-498504717701-sa-east-1",
    "key": "tests/fixtures/payrolls/paystub_001_canonical.pdf"
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
  "message": "Extraction triggered successfully"
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
tests/
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
2. `FetchDocument` valida que o PDF existe no S3
3. `ExtractPdfText` lê o PDF com PyMuPDF e persiste `raw_text.txt`
4. `LoadExtractionProfile` carrega o YAML do perfil versionado
5. `RunLLMExtraction` chama a OpenAI com Structured Outputs
6. `ValidateSchema` valida o JSON retornado
7. `PersistResult` grava `result.json` e `status.json`
8. Em caso de erro, `PersistFailure` grava `status.json` com falha

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
