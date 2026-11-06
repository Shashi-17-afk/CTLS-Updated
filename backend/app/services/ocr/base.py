from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, Field


class OCRItem(BaseModel):
    """Recognized segment/line with polygon coordinates and confidence."""

    text: str = Field(description="Extracted text string")
    confidence: Optional[float] = Field(
        default=None,
        description="Confidence score (0.0 to 1.0); None if engine does not provide confidence",
    )
    box: list[list[float]] = Field(
        description="4-point polygon coordinates [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]"
    )


class OCRResult(BaseModel):
    """Normalized OCR output across different engines."""

    text: str = Field(default="", description="Aggregated full-text output")
    lines: list[OCRItem] = Field(default_factory=list, description="Per-line OCR results")
    mean_confidence: Optional[float] = Field(
        default=None,
        description="Calculated average confidence across recognized text segments",
    )
    char_count: int = Field(default=0, ge=0)
    word_count: int = Field(default=0, ge=0)


class BaseOCREngine(ABC):
    """Abstract Base Class for pluggable local OCR engines."""

    @abstractmethod
    def extract(self, image: Any) -> OCRResult:
        """
        Executes local OCR inference on an image.

        Args:
            image: Image data as a numpy array, PIL Image, or raw bytes.
        Returns:
            OCRResult with extracted text, lines, bounding boxes, and confidence.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the engine runtime and weights are loaded and ready."""
        pass
