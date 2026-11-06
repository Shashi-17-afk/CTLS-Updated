"""Domain exceptions for document ingestion and validation."""


class IngestionError(Exception):
    """Base exception for document ingestion errors."""

    def __init__(self, message: str, error_code: str = "INGESTION_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class EmptyFileError(IngestionError):
    def __init__(self, message: str = "Uploaded file is empty.") -> None:
        super().__init__(message, error_code="EMPTY_FILE")


class FileTooLargeError(IngestionError):
    def __init__(self, max_bytes: int, actual_bytes: int) -> None:
        super().__init__(
            f"File size exceeds maximum allowed limit ({actual_bytes} > {max_bytes} bytes).",
            error_code="FILE_TOO_LARGE",
        )
        self.max_bytes = max_bytes
        self.actual_bytes = actual_bytes


class UnsupportedFormatError(IngestionError):
    def __init__(self, detected_type: str) -> None:
        super().__init__(
            f"Unsupported file format: {detected_type}. Allowed formats: PDF, PNG, JPEG, JPG.",
            error_code="UNSUPPORTED_FORMAT",
        )
        self.detected_type = detected_type


class MalformedDocumentError(IngestionError):
    def __init__(self, message: str = "Document structure is corrupt or malformed.") -> None:
        super().__init__(message, error_code="MALFORMED_DOCUMENT")


class EncryptedDocumentError(IngestionError):
    def __init__(self, message: str = "Password-protected or encrypted documents are not supported.") -> None:
        super().__init__(message, error_code="DOCUMENT_ENCRYPTED")


class ExcessivePagesError(IngestionError):
    def __init__(self, max_pages: int, actual_pages: int) -> None:
        super().__init__(
            f"Document exceeds maximum page limit ({actual_pages} > {max_pages} pages).",
            error_code="EXCESSIVE_PAGES",
        )
        self.max_pages = max_pages
        self.actual_pages = actual_pages
