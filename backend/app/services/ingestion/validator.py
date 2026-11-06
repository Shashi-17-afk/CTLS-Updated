import re
from pathlib import PurePath
from typing import Tuple

from backend.app.core.config import settings
from backend.app.services.ingestion.exceptions import (
    EmptyFileError,
    FileTooLargeError,
    UnsupportedFormatError,
)

# Magic bytes signatures
PDF_SIGNATURE = b"%PDF-"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SOI = b"\xff\xd8\xff"


class FileValidator:
    """Validates raw binary uploads for size, integrity, and true file signatures."""

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitizes an untrusted filename, stripping directory traversal and illegal characters."""
        if not filename or not filename.strip():
            return "unnamed_document"
        # Extract basename only to prevent directory traversal
        basename = PurePath(filename).name
        # Keep alphanumeric, dots, underscores, dashes
        clean_name = re.sub(r"[^\w\-.]", "_", basename)
        # Cap length at 255 characters
        return clean_name[:255] if clean_name else "unnamed_document"

    @classmethod
    def detect_and_validate(cls, content: bytes, filename: str) -> Tuple[str, str]:
        """
        Validates content size and determines true file type from magic bytes.

        Returns:
            Tuple[detected_file_type, sanitized_filename]
        Raises:
            EmptyFileError, FileTooLargeError, UnsupportedFormatError
        """
        safe_name = cls.sanitize_filename(filename)
        content_len = len(content)

        # 1. Size bounds check
        if content_len < settings.MIN_FILE_SIZE_BYTES:
            raise EmptyFileError(
                f"File content is too small or empty ({content_len} bytes < {settings.MIN_FILE_SIZE_BYTES} bytes minimum)."
            )

        if content_len > settings.MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(
                max_bytes=settings.MAX_FILE_SIZE_BYTES,
                actual_bytes=content_len,
            )

        # 2. Signature detection
        detected_format = cls._detect_magic_type(content)
        if not detected_format:
            raise UnsupportedFormatError(
                detected_type="Unknown / Non-supported binary signature"
            )

        if detected_format not in settings.ALLOWED_EXTENSIONS:
            raise UnsupportedFormatError(detected_type=detected_format)

        return detected_format, safe_name

    @staticmethod
    def _detect_magic_type(content: bytes) -> str | None:
        """Inspects byte markers without trusting client headers or extensions."""
        # PDF check: usually in the first 1024 bytes (allowing for minor preamble)
        header_sample = content[:1024]
        if PDF_SIGNATURE in header_sample:
            return "pdf"

        # PNG check: exact 8-byte signature
        if content.startswith(PNG_SIGNATURE):
            return "png"

        # JPEG check: Start Of Image (SOI) marker
        if content.startswith(JPEG_SOI):
            return "jpeg"

        return None
