import io
from typing import Optional, Tuple
from PIL import Image, UnidentifiedImageError

from backend.app.core.config import settings
from backend.app.schemas.document import (
    OCRLineResult,
    PageProcessingResult,
    PageStatus,
)
from backend.app.services.ingestion.exceptions import (
    FileTooLargeError,
    MalformedDocumentError,
)
from backend.app.services.ocr.base import BaseOCREngine


class ImageParser:
    """Safely decodes, validates, and runs local OCR on standalone image documents."""

    @staticmethod
    def parse(
        content: bytes,
        ocr_engine: Optional[BaseOCREngine] = None,
        enable_ocr: bool = True,
    ) -> Tuple[list[PageProcessingResult], list[str]]:
        """
        Validates the image stream, ensures image dimensions are safe,
        and optionally executes local OCR on the image.
        """
        warnings: list[str] = []
        try:
            image_stream = io.BytesIO(content)
            with Image.open(image_stream) as img:
                # 1. Structural integrity check
                img.verify()

            # Reopen to read metadata
            image_stream.seek(0)
            with Image.open(image_stream) as img:
                width, height = img.size

                # 2. Decompression bomb / dimension guard
                if width > settings.MAX_IMAGE_DIMENSION_PX or height > settings.MAX_IMAGE_DIMENSION_PX:
                    raise FileTooLargeError(
                        max_bytes=settings.MAX_IMAGE_DIMENSION_PX,
                        actual_bytes=max(width, height),
                    )

                if width < 10 or height < 10:
                    warnings.append(f"Image dimensions ({width}x{height}) are unusually small.")

            # 3. If OCR is disabled, return OCR_REQUIRED (Phase 2 behavior)
            if not enable_ocr or ocr_engine is None:
                page_result = PageProcessingResult(
                    page_number=1,
                    status=PageStatus.OCR_REQUIRED,
                    has_embedded_text=False,
                    is_scanned=True,
                    char_count=0,
                    word_count=0,
                    extracted_text=None,
                )
                return [page_result], warnings

            # 4. Execute local OCR on the image
            try:
                ocr_result = ocr_engine.extract(content)
                if ocr_result.text.strip():
                    page_result = PageProcessingResult(
                        page_number=1,
                        status=PageStatus.TEXT_EXTRACTED,
                        has_embedded_text=False,
                        is_scanned=True,
                        extraction_method="OCR",
                        ocr_confidence=ocr_result.mean_confidence,
                        char_count=ocr_result.char_count,
                        word_count=ocr_result.word_count,
                        extracted_text=ocr_result.text,
                        bounding_boxes=[
                            OCRLineResult(
                                text=line.text,
                                confidence=line.confidence,
                                box=line.box,
                            )
                            for line in ocr_result.lines
                        ],
                    )
                else:
                    page_result = PageProcessingResult(
                        page_number=1,
                        status=PageStatus.EMPTY_PAGE,
                        has_embedded_text=False,
                        is_scanned=True,
                        extraction_method="OCR",
                        ocr_confidence=None,
                        char_count=0,
                        word_count=0,
                        extracted_text=None,
                        bounding_boxes=[],
                    )
                    warnings.append("OCR detected no readable text on this image.")

                return [page_result], warnings

            except Exception as ocr_err:
                page_result = PageProcessingResult(
                    page_number=1,
                    status=PageStatus.PROCESSING_FAILED,
                    has_embedded_text=False,
                    is_scanned=True,
                    error_message=f"OCR execution failed: {type(ocr_err).__name__}",
                )
                warnings.append("Local OCR execution encountered an error.")
                return [page_result], warnings

        except (UnidentifiedImageError, OSError, ValueError) as err:
            raise MalformedDocumentError(f"Corrupt or unreadable image stream: {str(err)}") from err
