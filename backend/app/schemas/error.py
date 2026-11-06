from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Schema for safe, non-leaking error responses."""

    error_code: str = Field(description="Machine-readable error classification code")
    message: str = Field(description="Safe, user-facing error message")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the error occurred",
    )
    details: Optional[Any] = Field(
        default=None,
        description="Optional sanitized error details, excluding confidential document contents",
    )
