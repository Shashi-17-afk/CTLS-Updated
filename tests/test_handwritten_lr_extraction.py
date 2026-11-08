import pytest
from dataclasses import dataclass
from typing import Optional
from backend.app.services.extraction.erode.lr_sheet_extractor import ErodeLRSheetExtractor
from backend.app.schemas.erode_extraction import ErodeLRRow, ErodeLRSheet


@dataclass
class MockOCRItem:
    text: str
    box: list[list[float]]
    confidence: Optional[float] = 0.95


def test_extract_lr_sheet_tn40b3804_genuine_lrs_no_fabrication():
    """
    Verifies that TN40B3804 handwritten sheet extracts all 7 genuine LRs:
    30084, 30094, 30095, 30096, 30097, 30098, 30099
    and does NOT sequentially fabricate (e.g. 30085) for the jump from 30084 to 30094.
    """
    ocr_lines = [
        # Header items
        MockOCRItem("CT LOGISTICS SOLUTIONS", [[400.0, 50.0], [900.0, 50.0], [900.0, 90.0], [400.0, 90.0]], 0.98),
        MockOCRItem("Truck No: TN 40 B 3804", [[100.0, 120.0], [450.0, 120.0], [450.0, 150.0], [100.0, 150.0]], 0.95),
        MockOCRItem("Date: 29/01/26", [[1200.0, 120.0], [1450.0, 120.0], [1450.0, 150.0], [1200.0, 150.0]], 0.96),
        MockOCRItem("LR No.", [[100.0, 220.0], [250.0, 220.0], [250.0, 250.0], [100.0, 250.0]], 0.97),
        MockOCRItem("Party Name", [[350.0, 220.0], [600.0, 220.0], [600.0, 250.0], [350.0, 250.0]], 0.97),
        MockOCRItem("Bundles/Reels", [[1100.0, 220.0], [1300.0, 220.0], [1300.0, 250.0], [1100.0, 250.0]], 0.97),
        MockOCRItem("Weight in Kgs", [[1350.0, 220.0], [1600.0, 220.0], [1600.0, 250.0], [1350.0, 250.0]], 0.97),
        # 7 Genuine LR Rows
        # Row 1: LR 30084 (jump to 30094 next!)
        MockOCRItem("30084", [[100.0, 300.0], [220.0, 300.0], [220.0, 330.0], [100.0, 330.0]], 0.94),
        MockOCRItem("SRI BALAJI PAPERS 1250510601", [[350.0, 300.0], [900.0, 300.0], [900.0, 330.0], [350.0, 330.0]], 0.92),
        MockOCRItem("32 reels", [[1100.0, 300.0], [1220.0, 300.0], [1220.0, 330.0], [1100.0, 330.0]], 0.95),
        MockOCRItem("1480.0", [[1350.0, 300.0], [1480.0, 300.0], [1480.0, 330.0], [1350.0, 330.0]], 0.93),
        # Row 2: LR 30094
        MockOCRItem("30094", [[100.0, 380.0], [220.0, 380.0], [220.0, 410.0], [100.0, 410.0]], 0.95),
        MockOCRItem("MEENAKSHI ENTERPRISES 1250510602", [[350.0, 380.0], [900.0, 380.0], [900.0, 410.0], [350.0, 410.0]], 0.91),
        MockOCRItem("40 bundles", [[1100.0, 380.0], [1250.0, 380.0], [1250.0, 410.0], [1100.0, 410.0]], 0.94),
        MockOCRItem("1850.0", [[1350.0, 380.0], [1480.0, 380.0], [1480.0, 410.0], [1350.0, 410.0]], 0.94),
        # Row 3: LR 30095
        MockOCRItem("30095", [[100.0, 460.0], [220.0, 460.0], [220.0, 490.0], [100.0, 490.0]], 0.93),
        MockOCRItem("KAVITHA TRADERS 1250510603", [[350.0, 460.0], [850.0, 460.0], [850.0, 490.0], [350.0, 490.0]], 0.92),
        MockOCRItem("50 bundles", [[1100.0, 460.0], [1250.0, 460.0], [1250.0, 490.0], [1100.0, 490.0]], 0.95),
        MockOCRItem("2100.0", [[1350.0, 460.0], [1480.0, 460.0], [1480.0, 490.0], [1350.0, 490.0]], 0.94),
        # Row 4: LR 30096
        MockOCRItem("30096", [[100.0, 540.0], [220.0, 540.0], [220.0, 570.0], [100.0, 570.0]], 0.96),
        MockOCRItem("SARAVANA PACKAGING 1250510604", [[350.0, 540.0], [880.0, 540.0], [880.0, 570.0], [350.0, 570.0]], 0.93),
        MockOCRItem("60 reels", [[1100.0, 540.0], [1220.0, 540.0], [1220.0, 570.0], [1100.0, 570.0]], 0.95),
        MockOCRItem("2450.0", [[1350.0, 540.0], [1480.0, 540.0], [1480.0, 570.0], [1350.0, 570.0]], 0.95),
        # Row 5: LR 30097
        MockOCRItem("30097", [[100.0, 620.0], [220.0, 620.0], [220.0, 650.0], [100.0, 650.0]], 0.92),
        MockOCRItem("ROYAL PRINTERS 1250510605", [[350.0, 620.0], [850.0, 620.0], [850.0, 650.0], [350.0, 650.0]], 0.90),
        MockOCRItem("45 bundles", [[1100.0, 620.0], [1250.0, 620.0], [1250.0, 650.0], [1100.0, 650.0]], 0.94),
        MockOCRItem("1980.0", [[1350.0, 620.0], [1480.0, 620.0], [1480.0, 650.0], [1350.0, 650.0]], 0.93),
        # Row 6: LR 30098
        MockOCRItem("30098", [[100.0, 700.0], [220.0, 700.0], [220.0, 730.0], [100.0, 730.0]], 0.95),
        MockOCRItem("VICTORY AGENCIES 1250510606", [[350.0, 700.0], [850.0, 700.0], [850.0, 730.0], [350.0, 730.0]], 0.92),
        MockOCRItem("42 bundles", [[1100.0, 700.0], [1250.0, 700.0], [1250.0, 730.0], [1100.0, 730.0]], 0.95),
        MockOCRItem("1760.0", [[1350.0, 700.0], [1480.0, 700.0], [1480.0, 730.0], [1350.0, 730.0]], 0.94),
        # Row 7: LR 30099
        MockOCRItem("30099", [[100.0, 780.0], [220.0, 780.0], [220.0, 810.0], [100.0, 810.0]], 0.94),
        MockOCRItem("SHANTI PAPERS 1250510607", [[350.0, 780.0], [850.0, 780.0], [850.0, 810.0], [350.0, 810.0]], 0.91),
        MockOCRItem("43 reels", [[1100.0, 780.0], [1220.0, 780.0], [1220.0, 810.0], [1100.0, 810.0]], 0.95),
        MockOCRItem("1800.0", [[1350.0, 780.0], [1480.0, 780.0], [1480.0, 810.0], [1350.0, 810.0]], 0.94),
        # Footer
        MockOCRItem("Total  305  13420", [[1000.0, 960.0], [1500.0, 960.0], [1500.0, 990.0], [1000.0, 990.0]], 0.96),
        MockOCRItem("Signature", [[100.0, 1020.0], [300.0, 1020.0], [300.0, 1050.0], [100.0, 1050.0]], 0.95),
    ]

    sheet = ErodeLRSheetExtractor.extract(
        text="",
        page_number=7,
        ocr_lines=ocr_lines,
    )

    assert sheet.truck_number == "TN40B3804"
    assert sheet.page_number == 7
    assert len(sheet.rows) == 7

    extracted_lrs = [r.lr_number for r in sheet.rows]
    expected_lrs = ["30084", "30094", "30095", "30096", "30097", "30098", "30099"]
    assert extracted_lrs == expected_lrs, f"Expected {expected_lrs}, got {extracted_lrs}"

    # Verify 30085 was NOT fabricated
    assert "30085" not in extracted_lrs

    # Verify provenance preserved on each row
    for r in sheet.rows:
        assert r.source_page == 7
        assert r.raw_lr_text in expected_lrs
        assert r.confidence >= 0.90
        assert not r.needs_review
        assert r.review_reason is None


def test_extract_lr_sheet_tn88l6340_exactly_two_lrs():
    """
    Verifies that TN88L6340 handwritten sheet extracts EXACTLY the 2 genuine LRs:
    29795 and 29796.
    Does not invent 5 synthetic LRs.
    """
    ocr_lines = [
        MockOCRItem("CT LOGISTICS SOLUTIONS", [[400.0, 50.0], [900.0, 50.0], [900.0, 90.0], [400.0, 90.0]], 0.98),
        MockOCRItem("Truck No: TN 88 L 6340", [[100.0, 120.0], [450.0, 120.0], [450.0, 150.0], [100.0, 150.0]], 0.95),
        MockOCRItem("Date: 29/01/26", [[1200.0, 120.0], [1450.0, 120.0], [1450.0, 150.0], [1200.0, 150.0]], 0.96),
        MockOCRItem("LR No.", [[100.0, 220.0], [250.0, 220.0], [250.0, 250.0], [100.0, 250.0]], 0.97),
        MockOCRItem("Party Name", [[350.0, 220.0], [600.0, 220.0], [600.0, 250.0], [350.0, 250.0]], 0.97),
        MockOCRItem("Bundles/Reels", [[1100.0, 220.0], [1300.0, 220.0], [1300.0, 250.0], [1100.0, 250.0]], 0.97),
        MockOCRItem("Weight in Kgs", [[1350.0, 220.0], [1600.0, 220.0], [1600.0, 250.0], [1350.0, 250.0]], 0.97),
        # Exactly 2 LRs
        MockOCRItem("29795", [[100.0, 320.0], [220.0, 320.0], [220.0, 350.0], [100.0, 350.0]], 0.95),
        MockOCRItem("SRI BALAJI PAPERS 1250510550", [[350.0, 320.0], [900.0, 320.0], [900.0, 350.0], [350.0, 350.0]], 0.93),
        MockOCRItem("50 reels", [[1100.0, 320.0], [1250.0, 320.0], [1250.0, 350.0], [1100.0, 350.0]], 0.95),
        MockOCRItem("5200.0", [[1350.0, 320.0], [1480.0, 320.0], [1480.0, 350.0], [1350.0, 350.0]], 0.94),
        MockOCRItem("29796", [[100.0, 420.0], [220.0, 420.0], [220.0, 450.0], [100.0, 450.0]], 0.96),
        MockOCRItem("MUTHURAMAN AGENCIES 1250510551", [[350.0, 420.0], [900.0, 420.0], [900.0, 450.0], [350.0, 450.0]], 0.92),
        MockOCRItem("60 reels", [[1100.0, 420.0], [1250.0, 420.0], [1250.0, 450.0], [1100.0, 450.0]], 0.95),
        MockOCRItem("6100.0", [[1350.0, 420.0], [1480.0, 420.0], [1480.0, 450.0], [1350.0, 450.0]], 0.95),
        # Footer
        MockOCRItem("Total  110  11300", [[1000.0, 600.0], [1500.0, 600.0], [1500.0, 630.0], [1000.0, 630.0]], 0.96),
        MockOCRItem("Signature", [[100.0, 680.0], [300.0, 680.0], [300.0, 710.0], [100.0, 710.0]], 0.95),
    ]

    sheet = ErodeLRSheetExtractor.extract(
        text="",
        page_number=22,
        ocr_lines=ocr_lines,
    )

    assert sheet.truck_number == "TN88L6340"
    assert sheet.page_number == 22
    assert len(sheet.rows) == 2, f"Expected exactly 2 LRs, got {len(sheet.rows)}"

    extracted_lrs = [r.lr_number for r in sheet.rows]
    assert extracted_lrs == ["29795", "29796"]
    for r in sheet.rows:
        assert r.source_page == 22
        assert not r.needs_review


def test_missing_ocr_confidence_flags_needs_review():
    """
    Requirement 1: Never assign 0.90 confidence when OCR confidence is missing.
    Mark confidence as None / unknown and flag the LR for review.
    """
    ocr_lines = [
        MockOCRItem("LR No.", [[100.0, 200.0], [250.0, 200.0], [250.0, 230.0], [100.0, 230.0]], 0.95),
        MockOCRItem("Party Name", [[350.0, 200.0], [600.0, 200.0], [600.0, 230.0], [350.0, 230.0]], 0.95),
        # LR anchor with confidence=None
        MockOCRItem("30094", [[100.0, 300.0], [220.0, 300.0], [220.0, 330.0], [100.0, 330.0]], confidence=None),
        MockOCRItem("PARTY NAME 1250510888", [[350.0, 300.0], [800.0, 300.0], [800.0, 330.0], [350.0, 330.0]], 0.90),
    ]

    sheet = ErodeLRSheetExtractor.extract(
        text="",
        page_number=3,
        ocr_lines=ocr_lines,
    )

    assert len(sheet.rows) == 1
    row = sheet.rows[0]
    assert row.lr_number == "30094"
    assert row.confidence is None, f"Expected None for missing confidence, got {row.confidence}"
    assert row.needs_review is True
    assert "missing ocr confidence" in row.review_reason.lower()


def test_ocr_character_substitutions_flags_review_and_preserves_raw():
    """
    Requirement 3: If OCR character substitutions (O->0, I->1, b->6) are used,
    preserve the raw value and flag uncertain corrections for manual review.
    """
    ocr_lines = [
        MockOCRItem("LR No.", [[100.0, 200.0], [250.0, 200.0], [250.0, 230.0], [100.0, 230.0]], 0.95),
        MockOCRItem("Party Name", [[350.0, 200.0], [600.0, 200.0], [600.0, 230.0], [350.0, 230.0]], 0.95),
        # Row with substitution: '3O084' (capital O instead of 0)
        MockOCRItem("3O084", [[100.0, 300.0], [220.0, 300.0], [220.0, 330.0], [100.0, 330.0]], 0.88),
        MockOCRItem("BALAJI PAPERS 1250510601", [[350.0, 300.0], [800.0, 300.0], [800.0, 330.0], [350.0, 330.0]], 0.92),
    ]

    sheet = ErodeLRSheetExtractor.extract(
        text="",
        page_number=4,
        ocr_lines=ocr_lines,
    )

    assert len(sheet.rows) == 1
    row = sheet.rows[0]
    assert row.lr_number == "30084"
    assert row.raw_lr_text == "3O084"
    assert row.needs_review is True
    assert "character substitution" in row.review_reason.lower()


def test_non_lr_tokens_excluded_from_lr_extraction():
    """
    Requirement 2: Prevent weights, totals, dates, vehicle numbers, invoice numbers,
    and pincodes from being incorrectly extracted as LR numbers.
    """
    ocr_lines = [
        MockOCRItem("CT LOGISTICS SOLUTIONS", [[400.0, 50.0], [900.0, 50.0], [900.0, 90.0], [400.0, 90.0]], 0.98),
        MockOCRItem("Date: 29/01/26", [[100.0, 100.0], [300.0, 100.0], [300.0, 130.0], [100.0, 130.0]], 0.95),
        MockOCRItem("Truck No: TN40B3804", [[100.0, 140.0], [350.0, 140.0], [350.0, 170.0], [100.0, 170.0]], 0.95),
        MockOCRItem("LR No.", [[100.0, 220.0], [250.0, 220.0], [250.0, 250.0], [100.0, 250.0]], 0.97),
        MockOCRItem("Party Name", [[350.0, 220.0], [600.0, 220.0], [600.0, 250.0], [350.0, 250.0]], 0.97),
        # Non-LR tokens that must be skipped:
        # Weight float
        MockOCRItem("14323.8", [[100.0, 260.0], [220.0, 260.0], [220.0, 280.0], [100.0, 280.0]], 0.95),
        # Postal code
        MockOCRItem("638007", [[100.0, 285.0], [220.0, 285.0], [220.0, 305.0], [100.0, 305.0]], 0.95),
        # Invoice number starting with 125
        MockOCRItem("1250510477", [[100.0, 310.0], [220.0, 310.0], [220.0, 330.0], [100.0, 330.0]], 0.95),
        # Genuine LR
        MockOCRItem("30084", [[100.0, 350.0], [220.0, 350.0], [220.0, 380.0], [100.0, 380.0]], 0.95),
        MockOCRItem("SRI BALAJI PAPERS", [[350.0, 350.0], [800.0, 350.0], [800.0, 380.0], [350.0, 380.0]], 0.92),
        # Total line
        MockOCRItem("Total 14691.3", [[100.0, 500.0], [300.0, 500.0], [300.0, 530.0], [100.0, 530.0]], 0.95),
    ]

    sheet = ErodeLRSheetExtractor.extract(text="", page_number=9, ocr_lines=ocr_lines)
    assert len(sheet.rows) == 1
    assert sheet.rows[0].lr_number == "30084"


def test_text_fallback_30xxx_and_29xxx():
    """
    Verifies plain-text fallback extraction works for both 30xxx and 29xxx series.
    """
    text = (
        "CT LOGISTICS SOLUTIONS\n"
        "Truck No: TN40B3804 Pallipalayam Date: 29/01/26\n"
        "--------------------------------------------------\n"
        "30084  SRI BALAJI PAPERS (32) reels 1480.0\n"
        "       I. 1250510601\n"
        "30094  MEENAKSHI TRADERS (40) bundles 1850.0\n"
        "       I. 1250510602\n"
        "--------------------------------------------------\n"
        "Total 72 3330.0\n"
    )

    sheet = ErodeLRSheetExtractor.extract(text, page_number=8)
    assert len(sheet.rows) == 2
    assert sheet.rows[0].lr_number == "30084"
    assert sheet.rows[0].source_page == 8
    assert sheet.rows[0].package_count == 32
    assert sheet.rows[0].weight_kg == 1480.0
    assert sheet.rows[1].lr_number == "30094"
    assert sheet.rows[1].source_page == 8
    assert sheet.rows[1].package_count == 40
    assert sheet.rows[1].weight_kg == 1850.0


def test_header_metadata_and_phone_lr_separation():
    """
    Ensures:
    1. Driver Name, Driver Phone, Driver License, Owner Name, Owner Phone are cleanly extracted.
    2. Driver Name does not get overwritten by 'LR. No.'.
    3. Phone numbers (e.g. 636599577, 99446...) are not falsely extracted as 5-digit LR numbers.
    """
    from PIL import Image
    dummy_img = Image.new("RGB", (1754, 1240), color="white")
    ocr_lines = [
        MockOCRItem("CT LOGISTICS SOLUTIONS", [[800.0, 150.0], [1000.0, 150.0], [1000.0, 180.0], [800.0, 180.0]], 0.99),
        MockOCRItem("Truck No: TN33BK6799", [[150.0, 240.0], [450.0, 240.0], [450.0, 270.0], [150.0, 270.0]], 0.98),
        MockOCRItem("Owner Name: Kumar", [[200.0, 280.0], [450.0, 280.0], [450.0, 310.0], [200.0, 310.0]], 0.95),
        MockOCRItem("Owner Phone No.: 9843378461", [[1100.0, 280.0], [1450.0, 280.0], [1450.0, 310.0], [1100.0, 310.0]], 0.95),
        MockOCRItem("Driver Name : Cnnikrsin", [[200.0, 340.0], [450.0, 340.0], [450.0, 370.0], [200.0, 370.0]], 0.95),
        MockOCRItem("Driver Phone No. : 9526661559", [[1100.0, 340.0], [1450.0, 340.0], [1450.0, 370.0], [1100.0, 370.0]], 0.95),
        MockOCRItem("DL. No.: TN33-2022001", [[1500.0, 340.0], [1700.0, 340.0], [1700.0, 370.0], [1500.0, 370.0]], 0.95),
        # Table Header
        MockOCRItem("LR. No.:", [[150.0, 420.0], [300.0, 420.0], [300.0, 450.0], [150.0, 450.0]], 0.97),
        MockOCRItem("Party Name", [[450.0, 420.0], [700.0, 420.0], [700.0, 450.0], [450.0, 450.0]], 0.97),
        MockOCRItem("Weight in Kgs.", [[1300.0, 420.0], [1550.0, 420.0], [1550.0, 450.0], [1300.0, 450.0]], 0.97),
        # Table Row
        MockOCRItem("29789", [[150.0, 500.0], [280.0, 500.0], [280.0, 530.0], [150.0, 530.0]], 0.96),
        MockOCRItem("CV RAMAKRISHNAIER AND SONS", [[450.0, 500.0], [900.0, 500.0], [900.0, 530.0], [450.0, 530.0]], 0.95),
        MockOCRItem("19114.0", [[1300.0, 500.0], [1450.0, 500.0], [1450.0, 530.0], [1300.0, 530.0]], 0.95),
    ]

    sheet = ErodeLRSheetExtractor.extract(
        text="",
        page_number=1,
        page_image=dummy_img,
        ocr_lines=ocr_lines,
    )

    assert sheet.driver_name == "Cnnikrsin"
    assert sheet.driver_phone == "9526661559"
    assert sheet.driver_license == "TN33-2022001"
    assert sheet.owner_name == "Kumar"
    assert sheet.owner_phone == "9843378461"
    assert len(sheet.rows) == 1
    assert sheet.rows[0].lr_number == "29789"

