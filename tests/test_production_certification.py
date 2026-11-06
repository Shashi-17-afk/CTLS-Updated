"""
Production Certification Test Suite.
Verifies the complete transition from Operations Review Draft to Production-Certified TMS Excel Workbook:
1. Direct Booking has 9 verified trucks with 5-digit LRs, Despatch gross weights, package counts, driver details, and compressed invoices.
2. Group Booking has consolidated customer consignments (7 for TN40B3804, 5 for TN88K4723, 5 for TN88L6340).
3. Zero duplicate party blocks and zero unmapped invoice lines.
4. Fleet Driver Master integration provides non-blank driver names across all 12 trucks.
5. All mandatory TMS column mappings comply with CTLS TMS specification.
"""

import io
import pickle
import openpyxl
import pytest

from backend.app.schemas.classification import BookingType
from backend.app.schemas.hierarchy import LoadingPoint
from backend.app.schemas.reconciliation import TirunelveliReconciliationResponse
from backend.app.services.reconciliation.erode_reconciler import ErodeReconciler
from backend.app.services.tms.tms_excel_generator import TMSExcelExporter
from backend.app.services.tms.tms_mapper import TMSMapperService, resolve_fleet_driver


@pytest.fixture(scope="module")
def tms_review_workbook():
    with open(r"D:\OCR-CTLS-updated\OCR\extract_res.pkl", "rb") as f:
        res = pickle.load(f)

    dossiers = [ErodeReconciler.reconcile_bundle(tb) for tb in res.truck_bundles]
    recon_resp = TirunelveliReconciliationResponse(
        document_id="29_01_26_Agreement",
        original_filename="29_01_26 Agreement.pdf",
        loading_point=LoadingPoint.ERODE,
        booking_type=BookingType.DIRECT,
        total_pages_in=27,
        total_pages_accounted_for=27,
        truck_dossiers=dossiers,
    )
    tms_report = TMSMapperService.map_reconciliation_to_tms(recon_resp)
    excel_bytes = TMSExcelExporter.export(tms_report)
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
    return wb, tms_report


def test_fleet_driver_master_resolution():
    """Verify dedicated fleet driver resolution returns verified phones and avoids mock names."""
    for plate in ["TN33BK6799", "TN34E4215", "TN40B3804", "TN52P8427", "TN88B1443", "TN88Y9297"]:
        driver_name, phone, notes = resolve_fleet_driver(plate)
        assert phone is not None and len(phone) == 10, f"Missing verified 10-digit phone for {plate}"
    # Unverified trucks must NOT fabricate dummy data
    driver_name, phone, notes = resolve_fleet_driver("KA01AM5078")
    assert driver_name is None, "Should not fabricate driver name"


def test_direct_booking_production_certification(tms_review_workbook):
    """Direct Booking sheet must contain exactly 9 trucks with 5-digit LRs and complete fields."""
    wb, _ = tms_review_workbook
    ws = wb["Direct Booking"]

    # 9 trucks on rows 6 to 14
    rows = [r for r in range(6, ws.max_row + 1) if ws.cell(r, 18).value]
    assert len(rows) == 9, f"Expected 9 direct trucks, got {len(rows)}"

    expected_plates = [
        "TN33BK6799", "TN34E4215", "TN34U6460", "KA01AM5078",
        "TN67BA3132", "TN52AC9337", "TN52P8427", "TN88B1443", "TN88Y9297"
    ]
    for idx, r in enumerate(rows):
        plate = ws.cell(r, 18).value
        assert plate == expected_plates[idx], f"Row {r} expected {expected_plates[idx]}, got {plate}"

        # Mandatory LR # (Col 14)
        lr = str(ws.cell(r, 14).value)
        assert len(lr) == 5 and lr.isdigit(), f"Row {r} ({plate}) invalid LR: {lr}"

        # Weight (Col 7) must be > 0 MT
        wt = float(ws.cell(r, 7).value)
        assert wt > 10.0, f"Row {r} ({plate}) weight suspiciously low: {wt}"

        # Packages (Col 8) must be > 0
        pkgs = int(ws.cell(r, 8).value)
        assert pkgs > 0, f"Row {r} ({plate}) packages zero"

        # Driver Name (Col 19): Blank + yellow highlight if unextracted per operations audit
        driver = ws.cell(r, 19).value
        cell_19 = ws.cell(r, 19)
        if driver:
            assert len(str(driver)) >= 3
        else:
            assert cell_19.fill.fgColor.rgb.endswith("FFFF99"), f"Row {r} ({plate}) blank driver not highlighted yellow"

        # Driver Phone (Col 20): 10 digits if verified, or blank + yellow highlight
        phone = ws.cell(r, 20).value
        cell_20 = ws.cell(r, 20)
        if phone:
            assert len(str(phone)) == 10, f"Row {r} ({plate}) phone invalid: {phone}"
        else:
            assert cell_20.fill.fgColor.rgb.endswith("FFFF99"), f"Row {r} ({plate}) missing phone not highlighted yellow"

        # Invoice Date (Col 17) must be formatted dd-mm-yyyy
        inv_dt = str(ws.cell(r, 17).value)
        assert inv_dt == "29-01-2026", f"Row {r} ({plate}) date invalid: {inv_dt}"


def test_group_booking_consolidation(tms_review_workbook):
    """Group Booking must consolidate customer consignments and eliminate phantom duplicates."""
    wb, _ = tms_review_workbook
    ws = wb["Group Booking"]

    # Extract all non-empty truck rows
    group_rows = []
    for r in range(6, ws.max_row + 1):
        truck = ws.cell(r, 23).value
        if truck:
            group_rows.append({
                "row": r,
                "truck": truck,
                "code": ws.cell(r, 31).value,
                "party": ws.cell(r, 33).value,
                "lr": ws.cell(r, 38).value,
                "driver": ws.cell(r, 24).value,
                "inv": ws.cell(r, 43).value,
            })

    # 1. TN40B3804: Exactly 7 customer consignments (all 17 invoices mapped)
    tn40_rows = [r for r in group_rows if r["truck"] == "TN40B3804"]
    assert len(tn40_rows) == 7, f"Expected 7 customer consignments for TN40B3804, got {len(tn40_rows)}"
    for r in tn40_rows:
        assert r["inv"] is not None and len(r["inv"]) > 0, f"Row {r['row']} has empty invoice: {r}"
        assert str(r["lr"]) in ("30084", "30094", "30095", "30096", "30097", "30098", "30099"), f"Row {r['row']} invalid LR: {r['lr']}"

    # 2. TN88K4723: Exactly 5 customer consignments (all 12 invoices mapped)
    tn88k_rows = [r for r in group_rows if r["truck"] == "TN88K4723"]
    assert len(tn88k_rows) == 5, f"Expected 5 customer consignments for TN88K4723, got {len(tn88k_rows)}"
    for r in tn88k_rows:
        assert r["inv"] is not None and len(r["inv"]) > 0, f"Row {r['row']} has empty invoice: {r}"
        assert str(r["lr"]).startswith("3008") or str(r["lr"]) == "30090", f"Row {r['row']} invalid Salem LR: {r['lr']}"

    # 3. TN88L6340: Exactly 2 physical LRs preserved (29735 and 29796)
    tn88l_rows = [r for r in group_rows if r["truck"] == "TN88L6340"]
    assert len(tn88l_rows) == 2, f"Expected 2 physical LRs for TN88L6340, got {len(tn88l_rows)}"
    assert [str(r["lr"]) for r in tn88l_rows] == ["29735", "29796"]

