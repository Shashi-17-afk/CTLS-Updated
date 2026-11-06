from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class PageStatus(str, Enum):
    """Processing status for an individual document page."""

    TEXT_EXTRACTED = "TEXT_EXTRACTED"
    OCR_REQUIRED = "OCR_REQUIRED"
    EMPTY_PAGE = "EMPTY_PAGE"
    PROCESSING_FAILED = "PROCESSING_FAILED"


class DocumentOverallStatus(str, Enum):
    """Overall ingestion outcome for the document."""

    TEXT_EXTRACTED = "TEXT_EXTRACTED"
    OCR_REQUIRED = "OCR_REQUIRED"
    MIXED_CONTENT = "MIXED_CONTENT"
    VALIDATED_IMAGE = "VALIDATED_IMAGE"


class OCRLineResult(BaseModel):
    """Recognized line or word box with text, confidence, and polygon coordinates."""

    text: str = Field(description="Recognized text string")
    confidence: Optional[float] = Field(
        default=None,
        description="OCR confidence score between 0.0 and 1.0; null when unprovided",
    )
    box: list[list[float]] = Field(
        description="4-point polygon coordinates [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]"
    )


class PageProcessingResult(BaseModel):
    """Structured result for a single page."""

    page_number: int = Field(ge=1, description="1-indexed page number")
    status: PageStatus = Field(description="Page processing status")
    has_embedded_text: bool = Field(description="True if usable embedded text was found")
    is_scanned: bool = Field(description="True if page is a raster scan or image")
    extraction_method: Optional[str] = Field(
        default=None,
        description="Extraction technique: 'EMBEDDED_TEXT' or 'OCR'",
    )
    ocr_confidence: Optional[float] = Field(
        default=None,
        description="Average OCR confidence for the page (0.0 to 1.0); None for embedded text",
    )
    char_count: int = Field(default=0, ge=0, description="Number of extracted characters")
    word_count: int = Field(default=0, ge=0, description="Number of extracted words")
    extracted_text: Optional[str] = Field(
        default=None,
        description="Extracted embedded text or OCR text; null when page is empty or OCR produced no text",
    )
    bounding_boxes: Optional[list[OCRLineResult]] = Field(
        default=None,
        description="Per-line/word OCR bounding boxes and confidence scores",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if page processing failed",
    )


class DocumentIngestResponse(BaseModel):
    """Structured response for document ingestion."""

    document_id: str = Field(description="Unique UUID for the ingested document")
    original_filename: str = Field(description="Sanitized original document filename")
    file_type: str = Field(description="Detected file format (pdf, png, jpeg)")
    file_size_bytes: int = Field(ge=0, description="Document size in bytes")
    page_count: int = Field(ge=1, description="Total number of pages")
    overall_status: DocumentOverallStatus = Field(description="Aggregated document status")
    pages: list[PageProcessingResult] = Field(description="Per-page processing results")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings encountered during ingestion")
