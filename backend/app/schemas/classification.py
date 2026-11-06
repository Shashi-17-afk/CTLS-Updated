from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class LoadingPoint(str, Enum):
    """Allowed loading points."""

    TIRUNELVELI = "tirunelveli"
    ERODE = "erode"


class BookingType(str, Enum):
    """Booking types (PRD §5.2), with 'auto' for automated mixed-bundle classification."""

    DIRECT = "direct"
    GROUP = "group"
    AUTO = "auto"


class PageClassificationType(str, Enum):
    """Page-level document classification for logistics documents."""

    MATERIAL_INVOICE = "MATERIAL_INVOICE"
    EWAY_BILL = "EWAY_BILL"
    SECURITY_COPY = "SECURITY_COPY"
    LORRY_RECEIPT = "LORRY_RECEIPT"
    DESPATCH_SHEET = "DESPATCH_SHEET"  # Erode counterpart
    UNKNOWN_PAGE = "UNKNOWN_PAGE"


class PageClassificationResult(BaseModel):
    """Classification outcome for an individual page."""

    page_number: int = Field(ge=1, description="1-indexed page number")
    classification: PageClassificationType = Field(
        description="Predicted document classification type"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score for this classification",
    )
    detected_anchors: list[str] = Field(
        default_factory=list,
        description="Keyword anchors and cues supporting the classification",
    )
    is_ambiguous: bool = Field(
        default=False,
        description="True if classification is borderline or conflicting signals exist",
    )
    review_reason: Optional[str] = Field(
        default=None,
        description="Explanation if human review is advised",
    )
