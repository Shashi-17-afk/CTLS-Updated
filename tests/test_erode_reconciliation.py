import fitz
import pytest

from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.reconciliation import ReconciliationStatus
from backend.app.services.extraction.erode.despatch_extractor import ErodeDespatchExtractor
from backend.app.services.extraction.erode.lr_sheet_extractor import ErodeLRSheetExtractor
from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler
from tests.fixtures.synthetic_erode import (
    create_synthetic_erode_despatch_pdf,
    create_synthetic_erode_lr_sheet_pdf,
)


def test_erode_group_booking_worked_example_6_1():
    """Verifies complete reconciliation for Worked Example §6.1 (TN52L0517 group booking)."""
    # 1. Extract Despatch
    despatch_bytes = create_synthetic_erode_despatch_pdf(truck_no="TN52L0517", is_direct=False)
    doc_d = fitz.open(stream=despatch_bytes, filetype="pdf")
    despatch_sheet = ErodeDespatchExtractor.extract(doc_d[0].get_text(), page_number=2)
    doc_d.close()

    # 2. Extract LR Sheet
    lr_bytes = create_synthetic_erode_lr_sheet_pdf(truck_no="TN52 L0517", is_direct=False)
    doc_lr = fitz.open(stream=lr_bytes, filetype="pdf")
    lr_sheet = ErodeLRSheetExtractor.extract(doc_lr[0].get_text(), page_number=1)
    doc_lr.close()

    # 3. Reconcile
    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr_sheet,
        despatch_sheet=despatch_sheet,
        booking_type=BookingType.GROUP,
    )

    assert dossier.truck_number == "TN52L0517"
    assert dossier.loading_point == LoadingPoint.ERODE
    assert dossier.booking_type == BookingType.GROUP
    assert len(dossier.reconciled_consignments) == 3

    # Check totals: 60 packages, 26.694 MT
    assert dossier.truck_total_packages == 60
    assert dossier.truck_total_weight_mt == 26.694

    c1, c2, c3 = dossier.reconciled_consignments

    # LR 29738
    assert c1.lr_number_raw == "29738"
    assert c1.compressed_invoices_cell == "1250510477"
    assert c1.governing_weight_kg == 1354.0
    assert c1.governing_weight_mt == 1.354
    assert c1.lr_crosscheck_weight_kg == 1357.0
    assert not c1.weight_matches_lr  # Weight mismatch flag: 1354 vs 1357
    assert c1.freight_amount == 2505.0
    assert not c1.is_party_freight
    assert c1.eway_bills_cell == "521945263506"

    # LR 29739
    assert c2.lr_number_raw == "29739"
    assert c2.compressed_invoices_cell == "1250510478"
    assert c2.governing_weight_kg == 1290.0
    assert c2.governing_weight_mt == 1.290
    assert c2.freight_amount == 2387.0
    assert c2.eway_bills_cell == "561945263511"

    # LR 29740 (Multi-invoice roll-up and Bill-to vs delivery edge case)
    assert c3.lr_number_raw == "29740"
    assert c3.compressed_invoices_cell == "1250510479-480"  # §5.3 format
    assert c3.unique_invoices == ["1250510479", "1250510480"]
    assert c3.governing_weight_kg == 24050.0  # 4707 + 19343
    assert c3.governing_weight_mt == 24.050
    assert c3.freight_amount == 44493.0  # 8708 + 35785
    assert "551945263518" in c3.eway_bills_cell
    assert "561945263524" in c3.eway_bills_cell
    assert c3.bill_to_differs_from_delivery  # Siva Binding Works vs Muthuraman
    assert any("Bill-To differs" in n for n in c3.audit_notes)


def test_erode_direct_booking_worked_example_6_2():
    """Verifies complete reconciliation for Worked Example §6.2 (TN52AD9720 direct booking, Frt Amt 0)."""
    # 1. Extract Despatch
    despatch_bytes = create_synthetic_erode_despatch_pdf(truck_no="TN52AD9720", is_direct=True)
    doc_d = fitz.open(stream=despatch_bytes, filetype="pdf")
    despatch_sheet = ErodeDespatchExtractor.extract(doc_d[0].get_text(), page_number=2)
    doc_d.close()

    # 2. Extract LR Sheet
    lr_bytes = create_synthetic_erode_lr_sheet_pdf(truck_no="TN52AD9720", is_direct=True)
    doc_lr = fitz.open(stream=lr_bytes, filetype="pdf")
    lr_sheet = ErodeLRSheetExtractor.extract(doc_lr[0].get_text(), page_number=1)
    doc_lr.close()

    # 3. Reconcile
    dossier = ErodeReconciler.reconcile(
        lr_sheet=lr_sheet,
        despatch_sheet=despatch_sheet,
        booking_type=BookingType.DIRECT,
    )

    assert dossier.truck_number == "TN52AD9720"
    assert len(dossier.reconciled_consignments) == 1
    assert dossier.truck_total_packages == 48
    assert dossier.truck_total_weight_mt == 25.251

    c = dossier.reconciled_consignments[0]
    assert c.lr_number_raw == "29734"
    assert c.compressed_invoices_cell == "1250608568"
    assert c.governing_weight_kg == 25251.0
    assert c.governing_weight_mt == 25.251
    assert c.freight_amount == 0.0  # Party freight rule §5.4
    assert c.is_party_freight
    assert c.eway_bills_cell == "561945196361"
    assert c.bill_to_differs_from_delivery  # SDR PRINTERS vs ORIENT BLACKSWAN

