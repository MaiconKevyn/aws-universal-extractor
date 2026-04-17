# Universal Extractor

Pipeline assíncrona em AWS para extração estruturada de documentos PDF usando Step Functions, Lambda, S3 e OpenAI.

## MVP

- Entrada via endpoint HTTP assíncrono
- Documento de entrada armazenado em S3
- Extração de texto de PDF com PyMuPDF
- Perfil de extração versionado em YAML
- Saída persistida no mesmo diretório do documento em `extract/<profile>/<version>/<request_id>/`

## Payload de entrada

```json
{
  "document": {
    "bucket": "documents-prod",
    "key": "clients/acme/inbox/2026/04/cash_requirements.pdf"
  },
  "extraction_profile": {
    "id": "cash_requirements",
    "version": "v1"
  },
  "client_id": "acme",
  "document_id": "cash_requirements_2026_04",
  "idempotency_key": "acme-cash-requirements-v1",
  "metadata": {
    "source_system": "portal"
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
events/
  submit-extraction.json
tests/
```

## Perfil de extração

Cada perfil é versionado em um arquivo YAML, por exemplo `profiles/cash_requirements/v1.yml`.

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

## Variáveis de ambiente esperadas

- `DOCUMENTS_BUCKET_NAME`
- `OPENAI_API_KEY_SECRET_ARN`
- `OPENAI_API_KEY` para desenvolvimento local via `.env`
- `OPENAI_MODEL`
- `STATE_MACHINE_ARN`
- `PROFILES_ROOT` opcional

## Observações

- O runtime alvo está configurado como Python 3.13
- O `sam` ainda não está instalado nesta máquina
- A integração OpenAI foi scaffoldada usando Responses API + Structured Outputs
