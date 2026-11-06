import os
import pytest
import numpy as np
import cv2

from backend.app.schemas.erode_extraction import ErodeDespatchSheet
from backend.app.services.extraction.erode.despatch_extractor import ErodeDespatchExtractor
from backend.app.services.ocr.preprocessor import ImagePreprocessor
from backend.app.services.extraction.erode.service import ErodeExtractionService

FIXTURE_PDF = r"C:\Users\Admin\.gemini\antigravity\brain\b3befcc0-943f-4cfa-bc75-354343c8efd5\.user_uploaded\media_1793342843505_d5f5e857.pdf"

GROUND_TRUTH = [
    ("TN34D5532", 18769.9, 341, "bundles"),
    ("TN21U1899", 12647.2, 71, "bundles"),
    ("TN52K5837", 14797.0, 38, "reels"),
    ("TN59BA1080", 18160.4, 319, "bundles"),
    ("TN34R1832", 25927.7, 465, "bundles"),
    ("TN52J9329", 18593.0, 21, "reels"),
    ("TN52AD9720", 25251.0, 48, "reels"),
    ("TN52L0517", 26694.0, 60, "reels"),
    ("TN52H4793", 28498.9, 487, "bundles"),
    ("TN52H7792", 25935.7, 504, "bundles"),
]


def test_final_total_selection_over_godown_subtotals():
    """Verifies that the parser selects the final Total row, ignoring preceding godown subtotal lines."""
    text = """
    Seshsavee Paper And Boards Ltd, Erode - 638 007
    Despatch Details
    Godown   Bund   NetWt   GrossWt   No of Inv
    Pm5      152    5772.0  5821.0    4
    DPGSH    89     3000.0  3050.0    3
    Total    341    18530.4 18769.9   15
    Supervisor Signature (Godown)
    """
    sheet = ErodeDespatchExtractor.extract(text, page_number=3)
    assert sheet.total_bundles == 341
    assert sheet.total_gross_weight_kg == 18769.9
    assert sheet.total_net_weight_kg == 18530.4
    assert sheet.no_of_invoices == 15
    assert sheet.package_unit == "bundles"


def test_package_extraction_not_from_weight_or_freight():
    """Verifies package count is never derived from freight, row weights, or adjacent large numbers."""
    text = """
    Despatch Details
    121255029771  KAMADHENU VENTURES  MADURAI  996.8  1096  571945256064
    Total  319  18000.9  18160.4  12
    """
    sheet = ErodeDespatchExtractor.extract(text, page_number=9)
    assert sheet.total_bundles == 319
    assert sheet.total_bundles != 1096  # 1096 is freight
    assert sheet.total_bundles != 996   # 996.8 is line weight
    assert sheet.total_gross_weight_kg == 18160.4


def test_ocr_split_rows_handling():
    """Verifies that an OCR-split Total row (Total keyword on line 1, numeric values on line 2) is correctly parsed."""
    text = """
    Godown   Bund   NetWt   GrossWt   No of Inv
    Pm1-4    60     26694.0 26694.0
    Total
    60  26694.0  26694.0
    Supervisor Signature (Godown)
    """
    sheet = ErodeDespatchExtractor.extract(text, page_number=17)
    assert sheet.total_bundles == 60
    assert sheet.total_gross_weight_kg == 26694.0
    assert sheet.total_net_weight_kg == 26694.0
    assert sheet.package_unit == "reels"


def test_package_units_bundles_vs_reels_distinction():
    """Verifies that package units (bundles vs reels) are distinguished by weight physics and keywords."""
    # Low weight per package (~55 kg) -> bundles
    text_bundles = "Total 465 25695.2 25927.7"
    sheet_b = ErodeDespatchExtractor.extract(text_bundles, page_number=11)
    assert sheet_b.total_bundles == 465
    assert sheet_b.package_unit == "bundles"

    # High weight per package (~389 kg) -> reels
    text_reels = "Total 38 14797.0 14797.0"
    sheet_r = ErodeDespatchExtractor.extract(text_reels, page_number=7)
    assert sheet_r.total_bundles == 38
    assert sheet_r.package_unit == "reels"


def test_deskew_coordinate_order_and_shearing_prevention():
    """Verifies that ImagePreprocessor._deskew uses proper (x, y) coordinates and does not introduce false shears."""
    # Create a synthetic white image with horizontal text lines
    img = np.full((1200, 1700, 3), 255, dtype=np.uint8)
    for y in range(200, 1000, 60):
        cv2.line(img, (150, y), (1550, y), (0, 0, 0), 4)

    # Process image
    processed, skew_angle = ImagePreprocessor._deskew(img)
    # Skew angle on horizontal lines should be 0.0 (never -23 degrees)
    assert abs(skew_angle) < 0.5
    assert processed.shape == img.shape


def test_gross_weight_kg_representation():
    """Verifies gross weight is strictly represented in kg internally and converts to MT accurately."""
    text = "Total 71 12624.2 12647.2"
    sheet = ErodeDespatchExtractor.extract(text, page_number=5)
    assert sheet.total_gross_weight_kg == 12647.2
    # Verify metric tonnes calculation
    weight_mt = round(sheet.total_gross_weight_kg / 1000.0, 3)
    assert weight_mt == 12.647


def test_confidence_flagging_when_total_missing():
    """Verifies that if no total row can be extracted confidently, confidence is flagged rather than guessing."""
    text_no_totals = """
    Seshasayee Paper And Boards Ltd, Erode - 638 007
    Despatch Details
    1250510468 FOCUSPRINTFORMS COIMBATORE 1254 541945164771
    """
    sheet = ErodeDespatchExtractor.extract(text_no_totals, page_number=5)
    assert sheet.total_gross_weight_kg is None
    assert sheet.total_bundles is None
    assert sheet.confidence < 0.50


@pytest.mark.skipif(not os.path.exists(FIXTURE_PDF), reason="23-page fixture PDF not available")
def test_all_10_trucks_weight_and_package_ground_truth():
    """End-to-end integration test asserting all 10 trucks match Ground Truth for Gross Weight and Packages."""
    with open(FIXTURE_PDF, "rb") as f:
        pdf_bytes = f.read()

    extraction = ErodeExtractionService.process(pdf_bytes, "24_01_26 Agreement.pdf", enable_ocr=True)
    shipments = extraction.truck_bundles

    assert len(shipments) == 10, f"Expected 10 shipments, got {len(shipments)}"

    for idx, (exp_plate, exp_gross_wt, exp_pkgs, exp_unit) in enumerate(GROUND_TRUTH):
        shipment = shipments[idx]
        d = shipment.despatch_sheet
        assert d is not None, f"Shipment {idx+1} ({exp_plate}) has no Despatch sheet"

        # Assert Plate
        assert shipment.truck_number == exp_plate

        # Assert Booking Date (confirm Phase 2 date extraction remains unaffected)
        assert shipment.booking_date == "2026-01-24"

        # Assert Gross Weight
        assert d.total_gross_weight_kg == pytest.approx(exp_gross_wt, abs=0.1), (
            f"Truck {idx+1} ({exp_plate}) Gross Wt: {d.total_gross_weight_kg} != expected {exp_gross_wt}"
        )

        # Assert Packages
        assert d.total_bundles == exp_pkgs, (
            f"Truck {idx+1} ({exp_plate}) Packages: {d.total_bundles} != expected {exp_pkgs}"
        )

        # Assert Package Unit
        assert d.package_unit == exp_unit, (
            f"Truck {idx+1} ({exp_plate}) Package Unit: {d.package_unit} != expected {exp_unit}"
        )

