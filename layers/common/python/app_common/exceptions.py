class AppError(Exception):
    """Base application error."""


class RequestValidationError(AppError):
    """Raised when the submission payload is invalid."""


class ProfileNotFoundError(AppError):
    """Raised when the requested extraction profile does not exist."""


class ProfileValidationError(AppError):
    """Raised when a profile file is malformed."""


class DocumentExtractionError(AppError):
    """Raised when document text extraction fails."""


class StructuredOutputValidationError(AppError):
    """Raised when the extracted JSON does not match the schema."""
