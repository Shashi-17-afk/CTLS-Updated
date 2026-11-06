from typing import Any, Optional
from backend.app.services.ocr.base import BaseOCREngine, OCRItem, OCRResult


class MockOCREngine(BaseOCREngine):
    """Deterministic mock OCR engine for fast unit and regression tests."""

    def __init__(
        self,
        mock_text: str = "MOCK OCR RECOGNIZED TEXT 12345",
        mock_confidence: float = 0.95,
        fail: bool = False,
    ) -> None:
        self.mock_text = mock_text
        self.mock_confidence = mock_confidence
        self.fail = fail

    def is_available(self) -> bool:
        return not self.fail

    def extract(self, image_input: Any) -> OCRResult:
        if self.fail:
            raise RuntimeError("Mock OCR engine triggered test failure.")

        if not self.mock_text:
            return OCRResult(
                text="",
                lines=[],
                mean_confidence=None,
                char_count=0,
                word_count=0,
            )

        lines = [
            OCRItem(
                text=line,
                confidence=self.mock_confidence,
                box=[[10.0, 10.0], [200.0, 10.0], [200.0, 30.0], [10.0, 30.0]],
            )
            for line in self.mock_text.splitlines()
            if line.strip()
        ]

        return OCRResult(
            text=self.mock_text,
            lines=lines,
            mean_confidence=self.mock_confidence,
            char_count=len(self.mock_text),
            word_count=len(self.mock_text.split()),
        )
