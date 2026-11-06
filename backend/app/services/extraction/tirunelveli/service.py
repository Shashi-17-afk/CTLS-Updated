import logging
from typing import Optional

from backend.app.schemas.classification import (
    BookingType,
    LoadingPoint,
    PageClassificationType,
)
from backend.app.schemas.extraction import (
    TirunelveliExtractionResponse,
    TirunelveliPageExtractionResult,
)
from backend.app.services.classification.classifier import TirunelveliPageClassifier
from backend.app.services.extraction.tirunelveli.eway_extractor import EwayBillExtractor
from backend.app.services.extraction.tirunelveli.invoice_extractor import (
    MaterialInvoiceExtractor,
)
from backend.app.services.extraction.tirunelveli.lr_extractor import LorryReceiptExtractor
from backend.app.services.extraction.tirunelveli.security_copy_extractor import (
    SecurityCopyExtractor,
)
from backend.app.services.ingestion.service import DocumentIngestionService

logger = logging.getLogger(__name__)


class TirunelveliExtractionService:
    """Orchestrates page classification and raw field extraction for Tirunelveli documents.

    Ensures:
    - Zero pages are silently dropped.
    - All extracted values preserve page numbers, raw text, and bounding boxes.
    - Uncertain pages or fields are explicitly flagged for human review.
    """

    @classmethod
    def process(
        cls,
        content: bytes,
        original_filename: str,
        booking_type: Optional[BookingType] = None,
        enable_ocr: bool = True,
    ) -> TirunelveliExtractionResponse:
        """Processes a multi-page document for Tirunelveli loading point."""
        eff_booking_type = booking_type if (booking_type and booking_type != BookingType.AUTO) else BookingType.DIRECT
        # Step 1: Ingest document and extract text / bounding boxes
        ingest_result = DocumentIngestionService.process_document(
            content=content,
            original_filename=original_filename,
            enable_ocr=enable_ocr,
        )

        page_results: list[TirunelveliPageExtractionResult] = []
        global_flags: list[str] = []

        for page in ingest_result.pages:
            raw_text = page.extracted_text or ""
            boxes = page.bounding_boxes

            # Step 2: Classify the page
            classification = TirunelveliPageClassifier.classify_page(
                text=raw_text,
                page_number=page.page_number,
            )

            invoice_data = None
            eway_data = None
            security_data = None
            lr_data = None
            page_flags: list[str] = []

            if classification.is_ambiguous or classification.classification == PageClassificationType.UNKNOWN_PAGE:
                page_flags.append(
                    f"Page {page.page_number}: {classification.review_reason or 'Classification is ambiguous'}"
                )

            # Step 3: Extract fields based on classification
            if classification.classification == PageClassificationType.MATERIAL_INVOICE:
                invoice_data = MaterialInvoiceExtractor.extract(
                    text=raw_text,
                    page_number=page.page_number,
                    bounding_boxes=boxes,
                )
                if invoice_data.invoice_number.is_ambiguous:
                    page_flags.append(f"Page {page.page_number}: Ambiguous invoice number")
                if invoice_data.gross_weight_kg.value == 0.0:
                    page_flags.append(f"Page {page.page_number}: Missing or zero gross weight")

            elif classification.classification == PageClassificationType.EWAY_BILL:
                eway_data = EwayBillExtractor.extract(
                    text=raw_text,
                    page_number=page.page_number,
                    bounding_boxes=boxes,
                )
                if eway_data.eway_bill_number.is_ambiguous:
                    page_flags.append(f"Page {page.page_number}: Ambiguous E-way bill number")

            elif classification.classification == PageClassificationType.SECURITY_COPY:
                security_data = SecurityCopyExtractor.extract(
                    text=raw_text,
                    page_number=page.page_number,
                    bounding_boxes=boxes,
                )

            elif classification.classification == PageClassificationType.LORRY_RECEIPT:
                lr_data = LorryReceiptExtractor.extract(
                    text=raw_text,
                    page_number=page.page_number,
                    bounding_boxes=boxes,
                )
                if lr_data.lr_number.is_ambiguous:
                    page_flags.append(
                        f"Page {page.page_number}: Handwritten or non-standard LR number format"
                    )
                if lr_data.truck_number.is_ambiguous:
                    page_flags.append(f"Page {page.page_number}: Truck number missing on LR")

            elif classification.classification == PageClassificationType.UNKNOWN_PAGE:
                page_flags.append(
                    f"Page {page.page_number}: Document type could not be determined with confidence"
                )

            page_results.append(
                TirunelveliPageExtractionResult(
                    page_number=page.page_number,
                    classification=classification,
                    invoice_data=invoice_data,
                    eway_data=eway_data,
                    security_data=security_data,
                    lr_data=lr_data,
                    review_flags=page_flags,
                )
            )

        # Check document-level totals or flags
        classified_counts = {}
        for p in page_results:
            c_name = p.classification.classification.value
            classified_counts[c_name] = classified_counts.get(c_name, 0) + 1

        if PageClassificationType.UNKNOWN_PAGE.value in classified_counts:
            global_flags.append(
                f"{classified_counts[PageClassificationType.UNKNOWN_PAGE.value]} page(s) flagged for manual classification"
            )

        if classified_counts.get(PageClassificationType.LORRY_RECEIPT.value, 0) == 0:
            global_flags.append("Document bundle contains no recognizable Lorry Receipt (LR)")

        if classified_counts.get(PageClassificationType.MATERIAL_INVOICE.value, 0) == 0:
            global_flags.append("Document bundle contains no recognizable Material Invoice")

        return TirunelveliExtractionResponse(
            document_id=ingest_result.document_id,
            original_filename=ingest_result.original_filename,
            loading_point=LoadingPoint.TIRUNELVELI,
            booking_type=eff_booking_type,
            page_count=ingest_result.page_count,
            pages=page_results,
            global_review_flags=global_flags,
        )
