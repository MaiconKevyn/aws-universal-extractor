class OpenAIExtractionError(RuntimeError):
    """Base class for LLM extraction failures surfaced to Step Functions."""


class OpenAIRetryableError(OpenAIExtractionError):
    """Transient model-provider failure. Step Functions should retry this."""


class OpenAINonRetryableError(OpenAIExtractionError):
    """Permanent model-provider failure. Retrying will not help."""


class OpenAIResponseError(OpenAIRetryableError):
    """Provider returned an unusable response; safe to retry once."""


class DocumentTooLargeError(OpenAINonRetryableError):
    """Document exceeds the configured LLM chunking limits."""
