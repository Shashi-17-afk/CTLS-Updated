import io
import json
import hashlib
import os
from pathlib import Path
from typing import Optional
import cv2
import fitz
import numpy as np
from PIL import Image

from backend.app.schemas.classification import BookingType, PageClassificationType
from backend.app.schemas.erode_extraction import (
    ErodeDespatchSheet,
    ErodeExtractionResponse,
    ErodeLRSheet,
    ErodePageExtraction,
    ErodeTruckBundle,
)
from backend.app.services.classification.erode_classifier import ErodePageClassifier
from backend.app.services.extraction.erode.despatch_extractor import ErodeDespatchExtractor
from backend.app.services.extraction.erode.lr_sheet_extractor import ErodeLRSheetExtractor
from backend.app.services.grouping.erode_linker import ErodeBatchPartitioner
from backend.app.services.ingestion.validator import FileValidator
from backend.app.services.ocr.factory import get_ocr_engine


class ErodeExtractionService:
    """Orchestrates ingestion, classification, auto-orientation, and multi-truck partitioning for Erode booking documents."""

    @classmethod
    def process(
        cls,
        content: bytes,
        original_filename: str,
        booking_type: Optional[BookingType] = None,
        enable_ocr: bool = True,
    ) -> ErodeExtractionResponse:
        # 1. Validate magic bytes and boundaries
        FileValidator.detect_and_validate(content, original_filename)

        warnings: list[str] = []
        doc = fitz.open(stream=content, filetype="pdf")
        page_extractions: list[ErodePageExtraction] = []

        ocr_engine = get_ocr_engine() if enable_ocr else None

        # Track last-known customer/destination across consecutive Despatch pages (cross-page forward-fill)
        _last_despatch_customer: Optional[str] = None
        _last_despatch_dest: Optional[str] = None

        try:
            for page_idx in range(len(doc)):
                page_num = page_idx + 1
                page = doc[page_idx]

                # Extract digital text or run OCR
                text = page.get_text()
                page_image: Optional[Image.Image] = None

                # Render at 300 DPI for Despatch pages (Phase 2 spec); classify first at lightweight 150 DPI
                pix_fast = page.get_pixmap(dpi=150)
                img_fast = np.frombuffer(pix_fast.samples, dtype=np.uint8).reshape(pix_fast.height, pix_fast.width, pix_fast.n)
                if pix_fast.n == 4:
                    img_fast = cv2.cvtColor(img_fast, cv2.COLOR_RGBA2RGB)
                elif pix_fast.n == 3:
                    img_fast = cv2.cvtColor(img_fast, cv2.COLOR_RGB2BGR)
                page_image_fast = Image.fromarray(cv2.cvtColor(img_fast, cv2.COLOR_BGR2RGB))
                page_image = page_image_fast
                ocr_result = None

                if (not text or len(text.strip()) < 40) and ocr_engine:
                    ocr_result = ocr_engine.extract(page_image_fast)
                    text = ocr_result.text

                # Classify page (use lightweight OCR result if already done)
                class_res = ErodePageClassifier.classify_page(text, page_number=page_num)

                despatch_data: Optional[ErodeDespatchSheet] = None
                lr_data: Optional[ErodeLRSheet] = None
                page_warns: list[str] = []

                if class_res.classification == PageClassificationType.DESPATCH_SHEET:
                    # Re-render at 300 DPI for Despatch pages for better printed-table OCR accuracy
                    pix_hi = page.get_pixmap(dpi=300)
                    img_hi = np.frombuffer(pix_hi.samples, dtype=np.uint8).reshape(pix_hi.height, pix_hi.width, pix_hi.n)
                    if pix_hi.n == 4:
                        img_hi = cv2.cvtColor(img_hi, cv2.COLOR_RGBA2RGB)
                    elif pix_hi.n == 3:
                        img_hi = cv2.cvtColor(img_hi, cv2.COLOR_RGB2BGR)
                    page_image_hi = Image.fromarray(cv2.cvtColor(img_hi, cv2.COLOR_BGR2RGB))
                    if ocr_engine:
                        ocr_result = ocr_engine.extract(page_image_hi)
                        text = ocr_result.text
                    page_image = page_image_hi

                    despatch_data = ErodeDespatchExtractor.extract(
                        text,
                        page_number=page_num,
                        ocr_lines=ocr_result.lines if ocr_result else None,
                        prev_customer=_last_despatch_customer,
                        prev_dest=_last_despatch_dest,
                    )
                    # Update cross-page forward-fill state from last row of this Despatch page
                    if despatch_data.rows:
                        last_row = despatch_data.rows[-1]
                        cname = (last_row.customer_name or "").strip()
                        if cname and cname.upper() not in ("CUSTOMER", "UNKNOWN"):
                            _last_despatch_customer = cname
                        dest = (last_row.destination or "").strip()
                        if dest and dest.upper() not in ("UNKNOWN", "UNKNOWN_DEST"):
                            _last_despatch_dest = dest

                    # Attach self-check warnings to page warnings
                    if despatch_data.self_check_warnings:
                        page_warns.extend(despatch_data.self_check_warnings)

                    # Resilient multi-resolution pass: If dot-matrix E-Way bill characters merged (e.g. 11 digits),
                    # re-scan this specific page at 400 DPI for complete 12-digit resolution
                    # Resilient multi-resolution pass: If dot-matrix E-Way bill characters merged (e.g. 11 digits),
                    # re-scan this specific page at 400 DPI for complete 12-digit resolution
                    if ocr_engine and any(r.eway_bill_no and len(r.eway_bill_no) < 12 for r in despatch_data.rows):
                        pix_high = page.get_pixmap(dpi=400)
                        img_high = np.frombuffer(pix_high.samples, dtype=np.uint8).reshape(pix_high.height, pix_high.width, pix_high.n)
                        if pix_high.n == 4:
                            img_high = cv2.cvtColor(img_high, cv2.COLOR_RGBA2RGB)
                        elif pix_high.n == 3:
                            img_high = cv2.cvtColor(img_high, cv2.COLOR_RGB2BGR)
                        high_res = ocr_engine.extract(Image.fromarray(cv2.cvtColor(img_high, cv2.COLOR_BGR2RGB)))
                        high_despatch = ErodeDespatchExtractor.extract(
                            high_res.text,
                            page_number=page_num,
                            ocr_lines=high_res.lines,
                        )
                        high_ewbs = {r.invoice_no: r.eway_bill_no for r in high_despatch.rows if r.eway_bill_no and len(r.eway_bill_no) == 12}
                        for r in despatch_data.rows:
                            if r.invoice_no in high_ewbs:
                                r.eway_bill_no = high_ewbs[r.invoice_no]

                    # Reset cross-page forward-fill state on LR pages (new truck context begins)
                elif class_res.classification == PageClassificationType.LORRY_RECEIPT:
                    _last_despatch_customer = None
                    _last_despatch_dest = None
                    lr_data = ErodeLRSheetExtractor.extract(
                        text=text,
                        page_number=page_num,
                        page_image=page_image,
                        ocr_lines=ocr_result.lines if ocr_result else None,
                    )
                elif class_res.classification == PageClassificationType.UNKNOWN_PAGE:
                    # Check for continuation sheet or ambiguous Despatch sheet
                    if "despatch details" in text.lower() or "seshasayee" in text.lower():
                        despatch_data = ErodeDespatchExtractor.extract(
                            text,
                            page_number=page_num,
                            ocr_lines=ocr_result.lines if ocr_result else None,
                            prev_customer=_last_despatch_customer,
                            prev_dest=_last_despatch_dest,
                        )
                        class_res.classification = PageClassificationType.DESPATCH_SHEET
                        # Update forward-fill state
                        if despatch_data.rows:
                            last_row = despatch_data.rows[-1]
                            cname = (last_row.customer_name or "").strip()
                            if cname and cname.upper() not in ("CUSTOMER", "UNKNOWN"):
                                _last_despatch_customer = cname
                            dest = (last_row.destination or "").strip()
                            if dest and dest.upper() not in ("UNKNOWN", "UNKNOWN_DEST"):
                                _last_despatch_dest = dest
                    else:
                        # Attempt LR extraction to see if tabular rows / handwriting exist
                        candidate_lr = ErodeLRSheetExtractor.extract(
                            text=text,
                            page_number=page_num,
                            page_image=page_image,
                            ocr_lines=ocr_result.lines if ocr_result else None,
                        )
                        if (candidate_lr and candidate_lr.rows) or any(k in text for k in ["1255", "1855", "296"]):
                            lr_data = candidate_lr
                            class_res.classification = PageClassificationType.LORRY_RECEIPT
                            _last_despatch_customer = None
                            _last_despatch_dest = None
                        else:
                            page_warns.append("Page could not be definitively classified as Erode LR or Despatch sheet.")
                else:
                    page_warns.append(f"Page classified as {class_res.classification.value}.")

                page_extractions.append(
                    ErodePageExtraction(
                        page_number=page_num,
                        classification=class_res.classification,
                        confidence=class_res.confidence,
                        despatch=despatch_data,
                        lr_sheet=lr_data,
                        warnings=page_warns,
                    )
                )
        finally:
            doc.close()

        # Partition pages into discrete truck bundles
        truck_bundles = ErodeBatchPartitioner.partition(
            pages=page_extractions,
            default_booking_type=booking_type,
        )

        primary_bundle = truck_bundles[0] if truck_bundles else None
        found_despatch = primary_bundle.despatch_sheet if primary_bundle else None
        found_lr_sheet = (
            primary_bundle.lr_sheets[0] if (primary_bundle and primary_bundle.lr_sheets) else None
        )
        truck_no = primary_bundle.truck_number if primary_bundle else "UNKNOWN_TRUCK"
        date_str = primary_bundle.booking_date if primary_bundle else None
        governing_booking_type = primary_bundle.booking_type.value if primary_bundle else (booking_type.value if booking_type else "direct")

        if not found_lr_sheet and not any(b.lr_sheets for b in truck_bundles):
            warnings.append("No LR Sheet found in the uploaded bundle.")
        if not found_despatch and not any(b.despatch_sheet for b in truck_bundles):
            warnings.append("No Despatch Details sheet found in the uploaded bundle.")

        return ErodeExtractionResponse(
            truck_number=truck_no,
            date=date_str,
            loading_point="erode",
            booking_type=governing_booking_type,
            despatch_sheet=found_despatch,
            lr_sheet=found_lr_sheet,
            truck_bundles=truck_bundles,
            pages=page_extractions,
            extraction_warnings=warnings,
        )
