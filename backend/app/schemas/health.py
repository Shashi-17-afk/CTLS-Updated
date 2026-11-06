from datetime import datetime, timezone
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Schema for health-check response."""

    status: str = Field(default="healthy", description="Current service operational status")
    app_name: str = Field(description="Name of the running application")
    version: str = Field(description="Application version")
    environment: str = Field(description="Active runtime environment (e.g., development, production)")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Current UTC timestamp of the health check",
    )
