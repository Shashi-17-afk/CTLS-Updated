import datetime
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.extraction.erode.despatch_extractor import ErodeDespatchExtractor
from backend.app.services.extraction.erode.lr_sheet_extractor import ErodeLRSheetExtractor

client = TestClient(app, raise_server_exceptions=False)
PDF_PATH = Path("C:/Users/Admin/.gemini/antigravity/brain/b3befcc0-943f-4cfa-bc75-354343c8efd5/.user_uploaded/media_1793342843505_d5f5e857.pdf")


# ===========================================================================
# UNIT TESTS: Date Recognition, Variations, and Calendar Validation
# ===========================================================================


def test_date_full_label():
    text = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDate 24/01/2026   Lorry Number TN34D5532"
    assert ErodeDespatchExtractor._extract_date(text) == "2026-01-24"


def test_date_clipped_labels():
    # Clipped to Dat24/01/2026
    t1 = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDat24/01/2026   Lorry Number TN34D5532"
    assert ErodeDespatchExtractor._extract_date(t1) == "2026-01-24"

    # Clipped to Datt24/01/2026
    t2 = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDatt24/01/2026   Lorry Number TN34R1832"
    assert ErodeDespatchExtractor._extract_date(t2) == "2026-01-24"

    # Clipped to Dat:24/01/2026
    t3 = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDat:24/01/2026   Lorry Number TN52J9329"
    assert ErodeDespatchExtractor._extract_date(t3) == "2026-01-24"


def test_date_without_label_in_header():
    text = "Seshsavee Paper And Boards Ltd\nDespatch Details\n24/01/2026   Lorry Number TN34D5532"
    assert ErodeDespatchExtractor._extract_date(text) == "2026-01-24"


def test_date_single_digit_month_and_year():
    # 2-digit year (26 -> 2026) and single-digit month (1 -> 01)
    text = "CT LOGISTICS SOLUTIONS\nTruck No. TN34D5532   Pallipalayam   Date : 24/1/26\nLR. No.: Party Name"
    assert ErodeLRSheetExtractor._extract_date(text) == "2026-01-24"

    # Single-digit day and month with dots
    text_dot = "CT LOGISTICS SOLUTIONS\nTruck No. TN34D5532   Date : 4.1.26"
    assert ErodeLRSheetExtractor._extract_date(text_dot) == "2026-01-04"


def test_date_separators_hyphens_dots():
    assert ErodeDespatchExtractor._extract_date("Despatch Details\nDate 24-01-2026\nTN52K5837") == "2026-01-24"
    assert ErodeDespatchExtractor._extract_date("Despatch Details\nDate 24.01.2026\nTN52K5837") == "2026-01-24"
    assert ErodeDespatchExtractor._extract_date("Despatch Details\nDate 24/1/26\nTN52K5837") == "2026-01-24"


def test_date_invalid_month_rejection():
    # Month 00 must be rejected (the Truck 6 defect)
    t_zero_month = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDate 24/00/2026   TN52J9329"
    assert ErodeDespatchExtractor._extract_date(t_zero_month) is None

    # Month 13 must be rejected
    t_month_13 = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDate 24/13/2026   TN52J9329"
    assert ErodeDespatchExtractor._extract_date(t_month_13) is None


def test_date_invalid_day_rejection():
    # Day 00 must be rejected
    t_zero_day = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDate 00/01/2026   TN52J9329"
    assert ErodeDespatchExtractor._extract_date(t_zero_day) is None

    # Day 32 must be rejected
    t_day_32 = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDate 32/01/2026   TN52J9329"
    assert ErodeDespatchExtractor._extract_date(t_day_32) is None

    # Feb 29 on non-leap year (2025) must be rejected
    t_feb_nonleap = "Seshsavee Paper And Boards Ltd\nDespatch Details\nDate 29/02/2025   TN52J9329"
    assert ErodeDespatchExtractor._extract_date(t_feb_nonleap) is None


def test_signature_date_not_overriding_booking_date():
    text = (
        "Seshsavee Paper And Boards Ltd, Erode - 638 007\n"
        "Despatch Details\n"
        "Date 24/01/2026   Lorry Number TN52K5837   CT LOGISTICS SOLUTIONS\n"
        "1 1250510475   LEE PAPERS   SALEM   4079   551945239436\n"
        "Total   38   14797   14797\n"
        "TRANSPORTER SIGNATURE\n"
        "25/01/26\n"
    )
    # Must strictly return header booking date 2026-01-24, NOT the transporter signature date 25/01/26
    assert ErodeDespatchExtractor._extract_date(text) == "2026-01-24"


def test_multiple_dates_on_page():
    text = (
        "Seshsavee Paper And Boards Ltd, Erode - 638 007\n"
        "Despatch Details\n"
        "Dat24/01/2026   Lorry Number TN34D5532\n"
        "1 1250510466   YOGA AGENCIES   MADURAI 1104.0   1932   591945157440\n"
        "Supervisor Signature (Godown)\n"
        "TRANSPORTER SIGNATURE 27/01/26\n"
        "04/02/26\n"
    )
    assert ErodeDespatchExtractor._extract_date(text) == "2026-01-24"


def test_lr_sheet_pate_label():
    text = "CT LOGISTICS SOLUTIONS\n[pate : 24/01/26]\nTruck No. TN52L0517"
    assert ErodeLRSheetExtractor._extract_date(text) == "2026-01-24"


# ===========================================================================
# INTEGRATION TEST: Full 23-Page PDF End-to-End Date Verification
# ===========================================================================


@pytest.mark.slow
@pytest.mark.skipif(not PDF_PATH.exists(), reason="24_01_26 Agreement PDF fixture missing")
def test_all_10_trucks_have_valid_booking_date():
    with open(PDF_PATH, "rb") as f:
        pdf_bytes = f.read()

    resp = client.post(
        "/api/v1/bookings/reconcile?loading_point=erode&enable_ocr=true",
        files={"file": ("24_01_26_Agreement.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    data = resp.json()

    dossiers = data["truck_dossiers"]
    assert len(dossiers) == 10

    # Every single truck dossier must have booking date '2026-01-24'
    for idx, d in enumerate(dossiers, start=1):
        truck_no = d["truck_number"]
        b_date = d["booking_date"]
        assert b_date == "2026-01-24", f"Truck {idx} ({truck_no}) had booking_date={b_date!r}, expected '2026-01-24'"

        # Every consignment within the dossier must also have booking date '2026-01-24'
        for c in d["reconciled_consignments"]:
            assert c["booking_date"] == "2026-01-24", f"Consignment {c['consignment_id']} had date={c['booking_date']!r}"

