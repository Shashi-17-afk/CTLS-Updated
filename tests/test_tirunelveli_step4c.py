import fitz
from fastapi import status
from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from backend.app.schemas.reconciliation import ReconciliationStatus
from backend.app.services.reconciliation.range_compressor import (
    InvoiceRangeCompressor,
)
from tests.fixtures.synthetic_tirunelveli import (
    create_synthetic_duplicate_invoice_pdf,
    create_synthetic_tirunelveli_direct_pdf,
    create_synthetic_tirunelveli_group_pdf,
)

client = TestClient(app, raise_server_exceptions=False)


def test_range_compressor_prd_5_3():
    """Verifies that invoice ranges are compressed strictly in accordance with PRD §5.3."""
    # 1. Sequential sequence with differing 3-digit suffix (PRD §5.3 example 1)
    res1 = InvoiceRangeCompressor.compress(["1250510479", "1250510480"])
    assert res1 == "1250510479-480"

    # 2. Sequential sequence with differing 2-digit suffix (PRD §6.4 example)
    res2 = InvoiceRangeCompressor.compress(["2250501854", "2250501855", "2250501856"])
    assert res2 == "2250501854-56"

    # 3. 4-invoice sequence (PRD §6.3 Kunnamkulam example)
    res3 = InvoiceRangeCompressor.compress(["2250601397", "2250601398", "2250601399", "2250601400"])
    assert res3 == "2250601397-400"

    # 4. Non-sequential discrete numbers (PRD §5.3 example 2)
    res4 = InvoiceRangeCompressor.compress(["1001", "1005", "1009"])
    assert res4 == "1001, 1005, 1009"

    # 5. Mixed: range and discrete (PRD §5.3 example 3)
    res5 = InvoiceRangeCompressor.compress(["1001", "1002", "1003", "1008"])
    assert res5 == "1001-1003, 1008"

    # 6. Single invoice
    res6 = InvoiceRangeCompressor.compress(["2250501852"])
    assert res6 == "2250501852"


def test_kunnamkulam_direct_booking_reconciliation():
    """Tests full reconciliation of 9-page Kunnamkulam Direct Booking (PRD §6.3)."""
    pdf_bytes = create_synthetic_tirunelveli_direct_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/reconcile?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("Sl.no.5_TN52Y7426_Kunnamkulam_22.06.25.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["total_pages_in"] == 9
    assert data["total_pages_accounted_for"] == 9
    assert len(data["truck_dossiers"]) == 1

    dossier = data["truck_dossiers"][0]
    assert dossier["truck_number"] == "TN52Y7426"
    assert dossier["booking_date"] == "22/06/2025"

    # Consignment level checks
    assert len(dossier["reconciled_consignments"]) == 1
    c = dossier["reconciled_consignments"][0]

    assert c["lr_number_raw"] == "019427"
    assert c["lr_number_normalized"] == "19427"
    assert c["compressed_invoices_cell"] == "2250601397-400"
    assert len(c["unique_invoices"]) == 4

    # Weight: 17450.60 kg -> 17.451 MT
    assert c["governing_weight_kg"] == 17450.60
    assert c["governing_weight_mt"] == 17.451
    assert c["lr_crosscheck_weight_kg"] == 17450.60
    assert c["weight_matches_lr"] is True

    # Freight: 0.00 -> party freight
    assert c["freight_amount"] == 0.0
    assert c["is_party_freight"] is True
    assert any("PARTY_FREIGHT" in note for note in c["audit_notes"])

    # Packages & value
    assert c["total_packages"] == 160
    assert c["total_value_rs"] == 1346779.00

    # Bill To vs Delivery Place discrepancy check (PRD §5.4)
    assert c["bill_to_differs_from_delivery"] is True
    assert any("BILL_TO_DIFFERS_FROM_DELIVERY" in note for note in c["audit_notes"])


def test_trichy_group_booking_reconciliation():
    """Tests full reconciliation of 14-page Trichy Group Booking (PRD §6.4)."""
    pdf_bytes = create_synthetic_tirunelveli_group_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/reconcile?loading_point=tirunelveli&booking_type=group&enable_ocr=false",
        files={"file": ("TN30BD2189_Trichy_20.06.2025.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["total_pages_in"] == 14
    assert data["total_pages_accounted_for"] == 14

    dossier = data["truck_dossiers"][0]
    assert dossier["truck_number"] == "TN30BD2189"
    assert dossier["booking_date"] == "20/06/2025"

    # Truck totals
    assert dossier["truck_total_weight_mt"] == 16.130  # 1.957 + 4.092 + 10.081
    assert dossier["truck_total_packages"] == 272      # 33 + 69 + 170
    assert dossier["truck_total_value_rs"] == 1302407.00
    assert dossier["truck_total_freight_rs"] == 22279.00  # 2642 + 5524 + 14113

    # Security Copy cross-checks
    assert dossier["security_copy_present"] is True
    assert dossier["packages_tie_security_copy"] is True
    assert dossier["value_ties_security_copy"] is True

    # Consignment 1: LR 019406 - Weight Discrepancy (LR: 1955.9 vs Inv: 1956.90 kg)
    c1 = dossier["reconciled_consignments"][0]
    assert c1["lr_number_raw"] == "019406"
    assert c1["governing_weight_kg"] == 1956.90
    assert c1["governing_weight_mt"] == 1.957
    assert c1["lr_crosscheck_weight_kg"] == 1955.90
    assert c1["weight_matches_lr"] is False
    assert any("WEIGHT_DISCREPANCY" in note for note in c1["audit_notes"])
    assert c1["freight_amount"] == 2642.0

    # Consignment 3: LR 019408 - 3 Invoices rolled up
    c3 = dossier["reconciled_consignments"][2]
    assert c3["lr_number_raw"] == "019408"
    assert c3["compressed_invoices_cell"] == "2250501854-56"
    assert c3["governing_weight_mt"] == 10.081
    assert c3["freight_amount"] == 14113.00  # 4234 + 4234 + 5645


def test_duplicate_invoice_safety_in_reconciliation():
    """Tests that duplicate physical pages never inflate weight or value calculations in Step 4C."""
    pdf_bytes = create_synthetic_duplicate_invoice_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/reconcile?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("dup.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    c = data["truck_dossiers"][0]["reconciled_consignments"][0]

    # Exactly 2 physical pages were ingested
    assert c["physical_invoice_pages_count"] == 2
    assert c["duplicate_invoice_pages_detected"] is True

    # Weight is calculated once (1777.70 kg -> 1.778 MT), NEVER doubled to 3.555 MT
    assert c["governing_weight_kg"] == 1777.70
    assert c["governing_weight_mt"] == 1.778
    assert c["total_value_rs"] == 135610.00  # Calculated once, not doubled

    assert any("DUPLICATE_PAGES_SAFE" in note for note in c["audit_notes"])


def test_security_copy_mismatch_flagged():
    """Tests that package or value mismatches against Security Copy trigger review flags."""
    # Modify group PDF to have mismatched Security Copy packages (e.g. 250 instead of 272)
    doc = fitz.open(stream=create_synthetic_tirunelveli_group_pdf(), filetype="pdf")
    # Replace gate sheet on page 11 (index 10) cleanly
    doc.delete_page(10)
    page11 = doc.new_page(10, width=595, height=842)
    page11.insert_text((50, 70), """SESHASAYEE PAPER & BOARDS LTD TIRUNELVELI
SECURITY COPY
LorryNo: TN30BD2189
Date: 20/06/2025
Transporter Name : CT LOGISTICS SOLUTIONS
Total Bundles: 250
Total Net Wt: 15993.60
Total Value: 999999
""", fontsize=10)
    mismatched_pdf = doc.tobytes()
    doc.close()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/reconcile?loading_point=tirunelveli&booking_type=group&enable_ocr=false",
        files={"file": ("mismatched_gate.pdf", mismatched_pdf, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    dossier = data["truck_dossiers"][0]
    assert dossier["security_copy_present"] is True
    assert dossier["packages_tie_security_copy"] is False
    assert dossier["value_ties_security_copy"] is False
    assert any("PACKAGE_TOTAL_MISMATCH" in flag for flag in dossier["dossier_review_flags"])
    assert any("VALUE_TOTAL_MISMATCH" in flag for flag in dossier["dossier_review_flags"])
    assert dossier["dossier_status"] == ReconciliationStatus.REVIEW_REQUIRED_DISCREPANCY.value
