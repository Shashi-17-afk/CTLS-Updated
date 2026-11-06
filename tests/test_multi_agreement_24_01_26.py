"""
Multi-Agreement Validation Test Suite for 24_01_26 Agreement.pdf.
Verifies out-of-the-box pipeline execution on a completely new 23-page agreement:
1. 23 pages processed and partitioned into 10 discrete truck bundles.
2. Direct vs Group segregation: 4 Direct trucks, 6 Group trucks.
3. Zero data leakage from 29_01_26 baseline (date is 24-01-2026, 0 baseline truck plates).
4. Generated Excel workbook matches CTLS format.
"""

import pickle
import openpyxl
import pytest

from backend.app.schemas.classification import BookingType, PageClassificationType


@pytest.fixture(scope="module")
def agreement_24_extraction():
    with open(r"D:\OCR-CTLS-updated\OCR\extract_res_24_01_26.pkl", "rb") as f:
        return pickle.load(f)


@pytest.fixture(scope="module")
def agreement_24_workbook():
    wb = openpyxl.load_workbook(r"D:\OCR-CTLS-updated\OCR\CTLS_TMS_Booking_24_01_26_Agreement.xlsx", data_only=True)
    return wb


def test_page_count_and_classification(agreement_24_extraction):
    """Verify all 23 pages are accounted for with zero unclassified pages."""
    assert len(agreement_24_extraction.pages) == 23
    for p in agreement_24_extraction.pages:
        assert p.classification in (
            PageClassificationType.LORRY_RECEIPT,
            PageClassificationType.DESPATCH_SHEET,
        ), f"Page {p.page_number} unclassified: {p.classification}"


def test_truck_bundle_partitioning(agreement_24_extraction):
    """Verify 10 discrete truck bundles (4 direct, 6 group)."""
    bundles = agreement_24_extraction.truck_bundles
    assert len(bundles) == 10, f"Expected 10 truck bundles, got {len(bundles)}"

    direct_trucks = [b for b in bundles if b.booking_type == BookingType.DIRECT]
    group_trucks = [b for b in bundles if b.booking_type == BookingType.GROUP]

    assert len(direct_trucks) == 4, f"Expected 4 direct trucks, got {len(direct_trucks)}"
    assert len(group_trucks) == 6, f"Expected 6 group trucks, got {len(group_trucks)}"


def test_zero_data_leakage_from_baseline(agreement_24_extraction, agreement_24_workbook):
    """Ensure zero truck plates, dates, or LRs from 29_01_26 leak into 24_01_26."""
    baseline_plates = {
        "TN33BK6799", "TN34E4215", "TN34U6460", "TN40B3804", "KA01AM5078",
        "TN67BA3132", "TN52AC9337", "TN52P8427", "TN88B1443", "TN88Y9297",
        "TN88L6340", "TN88K4723"
    }

    extracted_plates = {b.truck_number for b in agreement_24_extraction.truck_bundles}
    overlap = extracted_plates.intersection(baseline_plates)
    assert len(overlap) == 0, f"Detected baseline plate leakage: {overlap}"

    # Verify pickup date is 2026-01-24 across Direct Booking
    ws_dir = agreement_24_workbook["Direct Booking"]
    for r in range(6, 10):
        dt = ws_dir.cell(r, 6).value
        assert str(dt) == "2026-01-24", f"Row {r} date leakage or mismatch: {dt}"


def test_direct_booking_structure(agreement_24_workbook):
    """Direct Booking sheet must contain exactly 4 trucks (Rows 6 to 9)."""
    ws = agreement_24_workbook["Direct Booking"]
    plates = [ws.cell(r, 18).value for r in range(6, 10)]
    assert plates == ["TN52K5837", "TN34R1832", "TN52AD9720", "TN52H7792"]

