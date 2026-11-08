import os
import sys
import time
from pathlib import Path

from backend.app.schemas.classification import LoadingPoint, BookingType
from backend.app.schemas.reconciliation import TirunelveliReconciliationResponse, ReconciliationStatus
from backend.app.schemas.extraction import TirunelveliPageExtractionResult
from backend.app.schemas.classification import PageClassificationResult
from backend.app.services.extraction.erode.service import ErodeExtractionService
from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler
from backend.app.services.tms.tms_mapper import TMSMapperService
from backend.app.services.tms.tms_excel_generator import TMSExcelExporter


def process_pdf(pdf_path: str, output_excel_path: str):
    print(f"\n==================================================")
    print(f"Processing: {pdf_path}")
    start_t = time.time()
    
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    filename = Path(pdf_path).name
    extract_res = ErodeExtractionService.process(
        content=pdf_bytes,
        original_filename=filename,
        booking_type=None,
        enable_ocr=True,
    )
    print(f"Extraction completed in {time.time() - start_t:.1f}s. Trucks found: {len(extract_res.truck_bundles)}")

    dossiers = []
    if extract_res.truck_bundles:
        for bundle in extract_res.truck_bundles:
            b_dossier = ErodeReconciler.reconcile_bundle(bundle)
            dossiers.append(b_dossier)
    else:
        dossier = ErodeReconciler.reconcile(
            lr_sheet=extract_res.lr_sheet,
            despatch_sheet=extract_res.despatch_sheet,
            booking_type=BookingType.GROUP,
        )
        dossiers.append(dossier)

    all_notes = [note for d in dossiers for c in d.reconciled_consignments for note in c.audit_notes]
    overall_status = ReconciliationStatus.CONFIRMED
    if any(
        c.status != ReconciliationStatus.CONFIRMED
        for d in dossiers
        for c in d.reconciled_consignments
    ):
        overall_status = ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY

    total_pages = len(extract_res.pages)
    ui_page_extractions = []
    for p in extract_res.pages:
        ui_page_extractions.append(
            TirunelveliPageExtractionResult(
                page_number=p.page_number,
                classification=PageClassificationResult(
                    page_number=p.page_number,
                    classification=p.classification,
                    confidence=p.confidence,
                    detected_anchors=[],
                ),
                review_flags=p.warnings,
            )
        )

    governing_booking_type = (dossiers[0].booking_type if dossiers else None) or BookingType.DIRECT

    reconciliation_resp = TirunelveliReconciliationResponse(
        document_id=extract_res.document_id,
        original_filename=filename,
        loading_point=LoadingPoint.ERODE,
        booking_type=governing_booking_type,
        truck_dossiers=dossiers,
        total_pages_in=total_pages,
        total_pages_accounted_for=total_pages,
        global_reconciliation_flags=all_notes,
        unassigned_pages=[],
        page_extractions=ui_page_extractions,
        overall_status=overall_status,
    )

    tms_review = TMSMapperService.map_reconciliation_to_tms(reconciliation_resp)
    excel_bytes = TMSExcelExporter.export(tms_review)

    with open(output_excel_path, "wb") as f:
        f.write(excel_bytes)

    print(f"Successfully generated Excel: {output_excel_path} ({len(excel_bytes)} bytes)")
    return tms_review


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    files = [
        ("benchmark/sets/24_01_26_Agreement.pdf", "benchmark/results/CTLS_TMS_Booking_TN34D5532_10trucks.xlsx"),
        ("benchmark/sets/10_09_26_agreement.pdf", "benchmark/results/CTLS_TMS_Booking_TN279599_7trucks.xlsx"),
        ("benchmark/sets/29_01_26_Agreement.pdf", "benchmark/results/CTLS_TMS_Booking_TN33BK6799_14trucks.xlsx"),
    ]

    for pdf, out in files:
        if target != "all" and target not in pdf:
            continue
        process_pdf(pdf, out)
