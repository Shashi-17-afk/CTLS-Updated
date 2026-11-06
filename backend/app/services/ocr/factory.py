from typing import Optional

from backend.app.core.config import settings
from backend.app.services.ocr.base import BaseOCREngine
from backend.app.services.ocr.engine_mock import MockOCREngine
from backend.app.services.ocr.engine_rapid import RapidPaddleOCREngine

_engine_instance: Optional[BaseOCREngine] = None


def get_ocr_engine(engine_type: Optional[str] = None, force_new: bool = False) -> BaseOCREngine:
    """
    Returns the singleton OCR engine instance based on application configuration.
    """
    global _engine_instance
    if _engine_instance is not None and not force_new:
        return _engine_instance

    target_type = (engine_type or settings.OCR_ENGINE).lower()

    if target_type == "mock":
        _engine_instance = MockOCREngine()
    elif target_type in ("rapidocr", "paddleocr", "paddle"):
        _engine_instance = RapidPaddleOCREngine()
    else:
        # Default fallback
        _engine_instance = RapidPaddleOCREngine()

    return _engine_instance


def set_ocr_engine(engine: BaseOCREngine) -> None:
    """Overrides the active OCR engine instance (for test mocking)."""
    global _engine_instance
    _engine_instance = engine


def reset_ocr_engine() -> None:
    """Resets the cached OCR engine instance."""
    global _engine_instance
    _engine_instance = None
