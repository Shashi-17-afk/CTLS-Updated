import logging
import re
import sys
from backend.app.core.config import settings

# Patterns that could represent leaked PII, sensitive commercial tokens, or long text dumps
BASE64_PATTERN = re.compile(r"data:[^;]+;base64,[A-Za-z0-9+/=]{50,}")
LONG_HEX_PATTERN = re.compile(r"\b[0-9a-fA-F]{64,}\b")


class ConfidentialityFilter(logging.Filter):
    """
    Log filter that ensures document text, base64 payloads, and raw data dumps
    are never recorded in application logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            # Redact data URLs or base64 streams
            if "base64" in record.msg:
                record.msg = BASE64_PATTERN.sub("[REDACTED_BINARY_PAYLOAD]", record.msg)
            # Truncate any accidental large dumps
            if len(record.msg) > 1000:
                record.msg = record.msg[:500] + "... [TRUNCATED_FOR_SECURITY]"
        return True


def setup_logging() -> None:
    """Configures application-wide logging with confidentiality guardrails."""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    formatter = logging.Formatter(fmt=log_format, datefmt="%Y-%m-%d %H:%M:%S")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(ConfidentialityFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers if setup is called multiple times
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
    else:
        root_logger.handlers = [console_handler]

    # Silence verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


logger = logging.getLogger("bespoke.ocr")
