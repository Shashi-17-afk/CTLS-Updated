"""Pluggable local OCR subsystem."""

from backend.app.services.ocr.base import BaseOCREngine, OCRItem, OCRResult
from backend.app.services.ocr.factory import get_ocr_engine, set_ocr_engine, reset_ocr_engine
from backend.app.services.ocr.engine_rapid import RapidPaddleOCREngine
from backend.app.services.ocr.engine_mock import MockOCREngine

__all__ = [
    "BaseOCREngine",
    "OCRItem",
    "OCRResult",
    "RapidPaddleOCREngine",
    "MockOCREngine",
    "get_ocr_engine",
    "set_ocr_engine",
    "reset_ocr_engine",
]
