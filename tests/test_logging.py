import logging
from backend.app.core.logging import ConfidentialityFilter


def test_confidentiality_filter_redacts_base64() -> None:
    """Verify base64 payloads are redacted from log messages."""
    log_filter = ConfidentialityFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Processing payload: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
        args=(),
        exc_info=None,
    )
    result = log_filter.filter(record)
    assert result is True
    assert "[REDACTED_BINARY_PAYLOAD]" in record.msg
    assert "iVBORw0KGgoAAAANSUhEUgAAAAE" not in record.msg


def test_confidentiality_filter_truncates_long_dumps() -> None:
    """Verify overly large log records are truncated to prevent document leakage."""
    log_filter = ConfidentialityFilter()
    long_text = "CONFIDENTIAL_INVOICE_DATA " * 100
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=25,
        msg=long_text,
        args=(),
        exc_info=None,
    )
    result = log_filter.filter(record)
    assert result is True
    assert "[TRUNCATED_FOR_SECURITY]" in record.msg
    assert len(record.msg) < len(long_text)
