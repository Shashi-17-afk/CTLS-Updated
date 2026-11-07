import io
import os
import openpyxl
from fastapi import status
from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from backend.app.schemas.classification import BookingType, LoadingPoint
from backend.app.schemas.reconciliation import (
    ConsignmentReconciliation,
    ReconciliationStatus,
    TirunelveliReconciliationResponse,
    TruckReconciliationDossier,
)
from backend.app.services.export.excel import TirunelveliExcelExporter
from tests.fixtures.synthetic_tirunelveli import (
    create_synthetic_duplicate_invoice_pdf,
    create_synthetic_tirunelveli_direct_pdf,
    create_synthetic_tirunelveli_group_pdf,
)

client = TestClient(app, raise_server_exceptions=False)


def test_mandatory_validation_on_excel_export():
    """Verifies that the /export-excel endpoint strictly validates required parameters."""
    pdf_bytes = create_synthetic_tirunelveli_direct_pdf()

    # 1. Missing loading_point -> HTTP 422
    resp1 = client.post(
        "/api/v1/bookings/tirunelveli/export-excel?booking_type=direct&enable_ocr=false",
        files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp1.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 2. Missing booking_type -> HTTP 422
    resp2 = client.post(
        "/api/v1/bookings/tirunelveli/export-excel?loading_point=tirunelveli&enable_ocr=false",
        files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp2.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 3. Loading point 'erode' rejected for current Tirunelveli milestone -> HTTP 422
    resp3 = client.post(
        "/api/v1/bookings/tirunelveli/export-excel?loading_point=erode&booking_type=direct&enable_ocr=false",
        files={"file": ("doc.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp3.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_kunnamkulam_excel_export():
    """Tests end-to-end Excel generation for 9-page Kunnamkulam Direct Booking (PRD §6.3)."""
    pdf_bytes = create_synthetic_tirunelveli_direct_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/export-excel?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("Sl.no.5_TN52Y7426_Kunnamkulam_22.06.25.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert 'filename="TN52Y7426_22.06.2025_reconciled.xlsx"' in resp.headers["content-disposition"]

    # Load openpyxl workbook from returned bytes
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    sheet_names = wb.sheetnames
    assert "Consignments" in sheet_names
    assert "Trip Summary & Gate Check" in sheet_names
    assert "Page Provenance & Accounting" in sheet_names

    ws_consignments = wb["Consignments"]

    # 1. Row 1: Notice Banner prominently labels provisional status
    banner = ws_consignments["A1"].value
    assert "PROVISIONAL LAYOUT" in banner
    assert "TN52Y7426" in resp.headers["content-disposition"]

    # 2. Row 2: Table Headers (20 columns)
    headers = [ws_consignments.cell(row=2, column=col).value for col in range(1, 21)]
    assert "Truck Number" in headers
    assert "LR Number" in headers
    assert "Invoices" in headers
    assert "Unique Invoices" in headers
    assert "Physical Inv Pages" in headers
    assert "Weight (MT)" in headers
    assert "Freight (Rs)" in headers
    assert "Freight Mode" in headers
    assert "Total Value (Rs)" in headers
    assert "Reconciliation Status" in headers
    assert "Audit / Review Notes" in headers
    assert "Source Provenance" in headers

    # 3. Row 3: Reconciled Consignment Data
    truck_val = ws_consignments["A3"].value
    date_val = ws_consignments["B3"].value
    lr_val = ws_consignments["C3"].value
    consignee_val = ws_consignments["D3"].value
    deliv_val = ws_consignments["E3"].value
    bill_to_val = ws_consignments["F3"].value
    invoices_val = ws_consignments["G3"].value
    uniq_invs_val = ws_consignments["H3"].value
    phys_pages_val = ws_consignments["I3"].value
    packs_val = ws_consignments["J3"].value
    packs_sum_val = ws_consignments["K3"].value
    wt_val = ws_consignments["L3"].value
    frt_val = ws_consignments["M3"].value
    frt_mode_val = ws_consignments["N3"].value
    val_val = ws_consignments["O3"].value
    ewb_val = ws_consignments["P3"].value
    status_val = ws_consignments["R3"].value
    notes_val = ws_consignments["S3"].value
    prov_val = ws_consignments["T3"].value

    assert truck_val == "TN52Y7426"
    assert date_val == "22/06/2025"
    # CRITICAL: Leading zero preserved in string format '@'
    assert lr_val == "019427"
    assert isinstance(lr_val, str)

    assert deliv_val.upper() == "KUNNAMKULAM"
    assert "Kausika" in consignee_val
    assert invoices_val == "2250601397-400"
    assert uniq_invs_val == 4
    assert phys_pages_val == 4
    assert packs_val == 160
    assert packs_sum_val == "160 reels"
    assert wt_val == 17.451
    assert frt_val == 0.0
    assert frt_mode_val == "Party Freight (0.00)"
    assert val_val == 1346779.00
    assert "501834108622" in ewb_val
    assert status_val == "REVIEW_REQUIRED_DISCREPANCY"
    assert "BILL_TO_DIFFERS_FROM_DELIVERY" in notes_val
    assert "PARTY_FREIGHT" in notes_val
    assert "LR: P9" in prov_val
    assert "Inv: P1-4" in prov_val
    assert "EWB: P5-8" in prov_val

    # 4. Sheet 2: Trip Summary & Gate Check
    ws_trip = wb["Trip Summary & Gate Check"]
    assert ws_trip["A3"].value == "TN52Y7426"
    assert ws_trip["F3"].value == 17.451  # Weight (MT)
    assert ws_trip["G3"].value == 160     # Packages
    assert ws_trip["J3"].value == "NO"    # Security copy present in direct booking

    # 5. Sheet 3: Page Provenance & Accounting
    ws_acc = wb["Page Provenance & Accounting"]
    assert ws_acc["C3"].value == 9  # Total Input Pages
    assert ws_acc["D3"].value == 9  # Accounted Pages
    assert "CONSERVED" in ws_acc["E3"].value


def test_trichy_excel_group_booking():
    """Tests Excel export for 14-page Trichy Group Booking (PRD §6.4)."""
    pdf_bytes = create_synthetic_tirunelveli_group_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/export-excel?loading_point=tirunelveli&booking_type=group&enable_ocr=false",
        files={"file": ("TN30BD2189_Trichy_20.06.2025.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    ws_consignments = wb["Consignments"]

    # 3 consignments: rows 3, 4, 5
    # Row 3: LR 019406 - Weight Discrepancy (LR 1955.9 vs Inv 1956.90 kg)
    assert ws_consignments["C3"].value == "019406"
    assert ws_consignments["L3"].value == 1.957
    assert ws_consignments["M3"].value == 2642.0
    assert "WEIGHT_DISCREPANCY" in ws_consignments["S3"].value
    # Visual fill on weight cell
    cell_wt = ws_consignments["L3"]
    assert cell_wt.fill.start_color.rgb in ("00FFF2CC", "FFF2CC")

    # Row 4: LR 019407
    assert ws_consignments["C4"].value == "019407"
    assert ws_consignments["L4"].value == 4.092
    assert ws_consignments["M4"].value == 5524.0

    # Row 5: LR 019408 - 3 invoices rolled up (2250501854-56)
    assert ws_consignments["C5"].value == "019408"
    assert ws_consignments["G5"].value == "2250501854-56"
    assert ws_consignments["H5"].value == 3  # Unique invoices
    assert ws_consignments["L5"].value == 10.081
    assert ws_consignments["M5"].value == 14113.0

    # Sheet 2: Gate Check Verification
    ws_trip = wb["Trip Summary & Gate Check"]
    assert ws_trip["A3"].value == "TN30BD2189"
    assert ws_trip["F3"].value == 16.130  # Total MT
    assert ws_trip["G3"].value == 272     # Total Packages
    assert ws_trip["H3"].value == 22279.0 # Total Freight
    assert ws_trip["I3"].value == 1302407.0 # Total Value
    assert ws_trip["J3"].value == "YES"   # Security Copy present
    assert ws_trip["K3"].value == "TIED"  # Packages tie gate sheet
    assert ws_trip["L3"].value == "TIED"  # Value ties gate sheet

    # Sheet 3: Page Accounting Invariant (14/14 pages)
    ws_acc = wb["Page Provenance & Accounting"]
    assert ws_acc["C3"].value == 14
    assert ws_acc["D3"].value == 14
    assert "CONSERVED" in ws_acc["E3"].value


def test_duplicate_invoice_excel_export():
    """Verifies that duplicate physical invoices are cleanly highlighted in Excel and never doubled."""
    pdf_bytes = create_synthetic_duplicate_invoice_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/export-excel?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("dup_bundle.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    ws = wb["Consignments"]

    # Consignment row:
    assert ws["H3"].value == 1  # Unique Invoices: 1
    assert ws["I3"].value == 2  # Physical Pages: 2
    assert ws["L3"].value == 1.778  # Single invoice weight in MT (not doubled to 3.555 MT)
    assert ws["O3"].value == 135610.00  # Single invoice value (not doubled)

    # Physical page cell is highlighted for staff attention
    phys_cell = ws["I3"]
    assert phys_cell.fill.start_color.rgb in ("00FFF2CC", "FFF2CC")
    assert "DUPLICATE_PAGES_SAFE" in ws["S3"].value


def test_unassigned_pages_displayed_in_excel():
    """Verifies that unassigned pages are transparently reported in Sheet 3 with reasons."""
    # Create a synthetic response directly with an unassigned page
    reconciled_resp = TirunelveliReconciliationResponse(
        document_id="test-doc-uuid",
        original_filename="sample_with_orphan.pdf",
        loading_point=LoadingPoint.TIRUNELVELI,
        booking_type=BookingType.DIRECT,
        total_pages_in=2,
        total_pages_accounted_for=2,
        truck_dossiers=[],
        unassigned_pages=[
            {
                "page_number": 2,
                "page_result": {
                    "page_number": 2,
                    "classification": {
                        "page_number": 2,
                        "classification": "UNKNOWN_PAGE",
                        "confidence": 0.3,
                        "detected_anchors": ["UNKNOWN_ANCHOR"],
                    },
                    "raw_text": "Sample unassignable page text without truck plate or date",
                },
                "unassigned_reason": "Missing identifiable truck number or pickup date",
            }
        ],
        global_reconciliation_flags=["TEST_FLAG"],
    )

    excel_bytes = TirunelveliExcelExporter.export(reconciled_resp)
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))

    ws_acc = wb["Page Provenance & Accounting"]
    # Check that unassigned page 2 is explicitly listed with its reason
    assert ws_acc["A7"].value == 2
    assert ws_acc["B7"].value == "UNKNOWN_PAGE"
    assert ws_acc["C7"].value == "Missing identifiable truck number or pickup date"
    assert "Anchors:" in ws_acc["D7"].value


def test_export_from_reconciliation_json_endpoint():
    """Verifies exporting an Excel workbook directly from Step 4C JSON payload."""
    pdf_bytes = create_synthetic_tirunelveli_direct_pdf()

    # Step 1: Run reconciliation to get JSON
    rec_resp = client.post(
        "/api/v1/bookings/tirunelveli/reconcile?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("direct.pdf", pdf_bytes, "application/pdf")},
    )
    assert rec_resp.status_code == status.HTTP_200_OK
    rec_json = rec_resp.json()

    # Step 2: Post JSON to /export-excel-from-reconciliation
    resp = client.post(
        "/api/v1/bookings/tirunelveli/export-excel-from-reconciliation",
        json=rec_json,
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "TN52Y7426" in resp.headers["content-disposition"]

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "Consignments" in wb.sheetnames
    assert wb["Consignments"]["C3"].value == "019427"


def test_synthetic_scanned_bundle_regression():
    """Regression test using TEST-m/synthetic_logistics_direct_bundle_test.pdf with OCR enabled.

    Validates all PRD expected values:
    - Truck TN52Y7426, LR 019427
    - 4 unique invoices (2250601397 to 1400), 4 E-Way Bills
    - 340 packages, 17.451 MT gross weight (17,450.60 kg)
    - Total invoice value ₹1,346,779
    - Zero unassigned pages (9/9 accounted for in truck dossier)
    """
    import os
    bundle_path = os.path.join("TEST-m", "synthetic_logistics_direct_bundle_test.pdf")
    if not os.path.exists(bundle_path):
        return

    with open(bundle_path, "rb") as f:
        pdf_bytes = f.read()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/export-excel?loading_point=tirunelveli&booking_type=direct&enable_ocr=true",
        files={"file": ("synthetic_logistics_direct_bundle_test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    ws_consignments = wb["Consignments"]
    assert ws_consignments["A3"].value == "TN52Y7426"
    assert ws_consignments["B3"].value == "22/06/2025"
    assert ws_consignments["C3"].value == "019427"
    assert ws_consignments["D3"].value == "SRI MEENAKSHI PAPER MART"
    assert "MADURAI" in ws_consignments["E3"].value
    assert ws_consignments["F3"].value == "KAUSIKA ENTERPRISES"
    assert ws_consignments["G3"].value == "2250601397-400"
    assert ws_consignments["H3"].value == 4
    assert ws_consignments["I3"].value == 4
    assert ws_consignments["J3"].value == 340
    assert "120 bales" in ws_consignments["K3"].value
    assert ws_consignments["L3"].value == 17.451
    assert ws_consignments["M3"].value == 0.0
    assert "Party Freight" in ws_consignments["N3"].value
    assert ws_consignments["O3"].value == 1346779.00
    assert "331084729101" in ws_consignments["P3"].value
    assert "331084729104" in ws_consignments["P3"].value
    assert ws_consignments["Q3"].value == "23/06/2025 23:59"
    assert ws_consignments["R3"].value == "REVIEW_REQUIRED_DISCREPANCY"
    assert "PARTY_FREIGHT" in ws_consignments["S3"].value
    assert "BILL_TO_DIFFERS_FROM_SHIP_TO" in ws_consignments["S3"].value
    assert "LR: P9; Inv: P1-4; EWB: P5-8" in ws_consignments["T3"].value
    assert ws_consignments["U3"].value == "SRI MEENAKSHI PAPER MART"

    # Verify professional Excel properties
    assert ws_consignments.freeze_panes == "A3"
    assert ws_consignments.auto_filter.ref is not None
    assert ws_consignments["O3"].number_format in ('"₹"#,##0.00', '₹#,##0.00', '#,##0.00')

    ws_acc = wb["Page Provenance & Accounting"]
    assert ws_acc["C3"].value == 9
    assert ws_acc["D3"].value == 9
    assert "Zero unassigned pages" in ws_acc["A7"].value


def test_group_booking_synthetic_bundle_regression():
    """Regression test for the 8-page Group Booking bundle (group_booking_synthetic_test_bundle.pdf):

    - Exactly 2 distinct LRs: 019427 and 019428.
    - Invoice 2250601397 and E-way bill 331084729101 link to LR 019427.
    - Invoice 2250601398 and E-way bill 331084729102 link to LR 019428.
    - LR 019427: 120 packages, 6.000 MT, Rs 100,000.
    - LR 019428: 80 packages, 4.000 MT, Rs 150,000.
    - Combined: 200 packages, 10.000 MT, Rs 250,000.
    - Strict conservation: 8/8 pages accounted for (Pages 1 and 8 as UNKNOWN_PAGE in unassigned pool).
    """
    bundle_path = os.path.join("TEST-m", "group_booking_synthetic_test_bundle.pdf")
    if not os.path.exists(bundle_path):
        pytest.skip(f"Test fixture not found: {bundle_path}")

    with open(bundle_path, "rb") as f:
        pdf_bytes = f.read()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/export-excel?loading_point=tirunelveli&booking_type=group&enable_ocr=false",
        files={"file": ("group_booking_synthetic_test_bundle.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))

    # 1. Consignments sheet
    ws_consignments = wb["Consignments"]
    # Row 3: LR 019427
    assert ws_consignments["A3"].value == "TN52Y7426"
    assert ws_consignments["B3"].value == "22/06/2025"
    assert ws_consignments["C3"].value == "019427"
    assert ws_consignments["D3"].value == "Sri Meenakshi Paper Mart"
    assert ws_consignments["F3"].value == "Kausika Enterprises"
    assert ws_consignments["G3"].value == "2250601397"
    assert ws_consignments["H3"].value == 1
    assert ws_consignments["J3"].value == 120
    assert ws_consignments["L3"].value == 6.0
    assert ws_consignments["M3"].value == 0.0
    assert ws_consignments["O3"].value == 100000.0
    assert ws_consignments["P3"].value == "331084729101"
    assert ws_consignments["Q3"].value == "23/06/2025 23:59"
    assert ws_consignments["T3"].value == "LR: P2; Inv: P3; EWB: P4"

    # Row 4: LR 019428
    assert ws_consignments["A4"].value == "TN52Y7426"
    assert ws_consignments["B4"].value == "22/06/2025"
    assert ws_consignments["C4"].value == "019428"
    assert ws_consignments["D4"].value == "South Star Traders"
    assert ws_consignments["F4"].value == "Kausika Enterprises"
    assert ws_consignments["G4"].value == "2250601398"
    assert ws_consignments["H4"].value == 1
    assert ws_consignments["J4"].value == 80
    assert ws_consignments["L4"].value == 4.0
    assert ws_consignments["M4"].value == 0.0
    assert ws_consignments["O4"].value == 150000.0
    assert ws_consignments["P4"].value == "331084729102"
    assert ws_consignments["Q4"].value == "23/06/2025 23:59"
    assert ws_consignments["T4"].value == "LR: P5; Inv: P6; EWB: P7"

    # 2. Trip Summary sheet
    ws_trip = wb["Trip Summary & Gate Check"]
    assert ws_trip["A3"].value == "TN52Y7426"
    assert ws_trip["E3"].value == 2
    assert ws_trip["F3"].value == 10.0
    assert ws_trip["G3"].value == 200
    assert ws_trip["H3"].value == 0.0
    assert ws_trip["I3"].value == 250000.0

    # 3. Page Accounting sheet
    ws_acc = wb["Page Provenance & Accounting"]
    assert ws_acc["C3"].value == 8
    assert ws_acc["D3"].value == 8
    assert "CONSERVED" in ws_acc["E3"].value


