import time
import uuid
from typing import Optional

from backend.app.core.config import settings
from backend.app.core.logging import logger
from backend.app.schemas.document import (
    DocumentIngestResponse,
    DocumentOverallStatus,
    PageStatus,
)
from backend.app.services.ingestion.image_parser import ImageParser
from backend.app.services.ingestion.pdf_parser import PDFParser
from backend.app.services.ingestion.validator import FileValidator
from backend.app.services.ocr.factory import get_ocr_engine


class DocumentIngestionService:
    """Orchestrates document validation, format detection, embedded text extraction, and local OCR."""

    @classmethod
    def process_document(
        cls,
        content: bytes,
        original_filename: str,
        enable_ocr: Optional[bool] = None,
    ) -> DocumentIngestResponse:
        """
        Executes the ingestion and text-extraction pipeline on in-memory binary data.
        If enable_ocr is True, scanned pages and standalone images are processed with local OCR.
        """
        start_time = time.perf_counter()
        doc_id = str(uuid.uuid4())

        use_ocr = settings.OCR_ENABLED if enable_ocr is None else enable_ocr
        ocr_engine = get_ocr_engine() if use_ocr else None

        # 1. Validation and signature detection
        detected_type, safe_filename = FileValidator.detect_and_validate(
            content=content,
            filename=original_filename,
        )

        # 2. Branch parsing based on verified signature
        if detected_type == "pdf":
            pages, warnings = PDFParser.parse(
                content=content,
                ocr_engine=ocr_engine,
                enable_ocr=use_ocr,
            )
        elif detected_type in ("png", "jpeg"):
            pages, warnings = ImageParser.parse(
                content=content,
                ocr_engine=ocr_engine,
                enable_ocr=use_ocr,
            )
        else:
            pages, warnings = [], ["Unrecognized document format."]

        # 3. Determine aggregated document status
        overall_status = cls._determine_overall_status(detected_type, pages, use_ocr)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # 4. Safe logging (Never log document text or sensitive field values)
        logger.info(
            "Ingested doc_id=%s format=%s pages=%d status=%s size_bytes=%d duration_ms=%.2f",
            doc_id,
            detected_type,
            len(pages),
            overall_status.value,
            len(content),
            elapsed_ms,
        )

        return DocumentIngestResponse(
            document_id=doc_id,
            original_filename=safe_filename,
            file_type=detected_type,
            file_size_bytes=len(content),
            page_count=len(pages),
            overall_status=overall_status,
            pages=pages,
            warnings=warnings,
        )

    @staticmethod
    def _determine_overall_status(
        file_type: str, pages: list, enable_ocr: bool
    ) -> DocumentOverallStatus:
        if not pages:
            return DocumentOverallStatus.OCR_REQUIRED

        if not enable_ocr and file_type in ("png", "jpeg"):
            return DocumentOverallStatus.VALIDATED_IMAGE

        text_pages = sum(1 for p in pages if p.status == PageStatus.TEXT_EXTRACTED)
        ocr_req_pages = sum(1 for p in pages if p.status == PageStatus.OCR_REQUIRED)
        empty_pages = sum(1 for p in pages if p.status == PageStatus.EMPTY_PAGE)

        if text_pages == len(pages):
            return DocumentOverallStatus.TEXT_EXTRACTED

        if ocr_req_pages == len(pages):
            return DocumentOverallStatus.OCR_REQUIRED

        if text_pages > 0 and (ocr_req_pages > 0 or empty_pages > 0):
            return DocumentOverallStatus.MIXED_CONTENT

        if file_type in ("png", "jpeg"):
            return DocumentOverallStatus.VALIDATED_IMAGE

        if empty_pages == len(pages):
            return DocumentOverallStatus.OCR_REQUIRED

        return DocumentOverallStatus.MIXED_CONTENT
