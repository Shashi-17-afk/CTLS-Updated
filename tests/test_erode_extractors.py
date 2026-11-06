import fitz
import pytest
from PIL import Image

from backend.app.services.extraction.erode.despatch_extractor import ErodeDespatchExtractor
from backend.app.services.extraction.erode.lr_sheet_extractor import ErodeLRSheetExtractor
from backend.app.services.ocr.cropper import LRImageCropper
from tests.fixtures.synthetic_erode import (
    create_synthetic_erode_despatch_pdf,
    create_synthetic_erode_lr_sheet_pdf,
)


def test_extract_erode_despatch_group_booking():
    """Verifies extraction of Erode Despatch Details for Worked Example §6.1."""
    pdf_bytes = create_synthetic_erode_despatch_pdf(is_direct=False)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = doc[0].get_text()
    doc.close()

    sheet = ErodeDespatchExtractor.extract(text, page_number=1)
    assert sheet.truck_number == "TN52L0517"
    assert sheet.date == "2026-01-24"
    assert len(sheet.rows) == 4

    # Row 1: 1250510477
    r1 = sheet.rows[0]
    assert r1.invoice_no == "1250510477"
    assert "LAKSHMI COTTAGE" in r1.customer_name
    assert r1.destination == "CHENNAI"
    assert r1.handwritten_weight_kg == 1354.0
    assert r1.freight_amount == 2505.0
    assert r1.eway_bill_no == "521945263506"

    # Row 3 & 4: 1250510479 & 1250510480 (roll into LR 29740)
    r3 = sheet.rows[2]
    r4 = sheet.rows[3]
    assert r3.invoice_no == "1250510479"
    assert r3.handwritten_weight_kg == 4707.0
    assert r3.freight_amount == 8708.0

    assert r4.invoice_no == "1250510480"
    assert r4.handwritten_weight_kg == 19343.0
    assert r4.freight_amount == 35785.0

    # Totals
    assert sheet.total_bundles == 60
    assert sheet.total_gross_weight_kg == 26694.0
    assert sheet.confidence >= 0.95


def test_extract_erode_despatch_direct_booking():
    """Verifies extraction of Erode Despatch Details for Worked Example §6.2 (Frt Amt 0)."""
    pdf_bytes = create_synthetic_erode_despatch_pdf(is_direct=True)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = doc[0].get_text()
    doc.close()

    sheet = ErodeDespatchExtractor.extract(text, page_number=1)
    assert sheet.truck_number == "TN52AD9720"
    assert len(sheet.rows) == 1

    r = sheet.rows[0]
    assert r.invoice_no == "1250608568"
    assert "SDR PRINTERS" in r.customer_name
    assert r.destination == "GHAZIABAD"
    assert r.handwritten_weight_kg == 25251.0
    assert r.freight_amount == 0.0  # Party freight
    assert r.eway_bill_no == "561945196361"

    assert sheet.total_bundles == 48
    assert sheet.total_gross_weight_kg == 25251.0


def test_extract_erode_lr_sheet_group_booking():
    """Verifies extraction of handwritten LR sheet for Worked Example §6.1."""
    pdf_bytes = create_synthetic_erode_lr_sheet_pdf(is_direct=False)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = doc[0].get_text()
    doc.close()

    sheet = ErodeLRSheetExtractor.extract(text, page_number=1)
    assert sheet.truck_number == "TN52L0517"
    assert sheet.destination == "Chennai"
    assert "NATHIYA" in sheet.owner_name
    assert sheet.owner_phone == "9698422778"
    assert "MUTHUMANI" in sheet.driver_name
    assert sheet.driver_phone == "9698422771"
    assert sheet.driver_license == "2935"

    assert len(sheet.rows) == 3

    # LR 29738
    lr1 = sheet.rows[0]
    assert lr1.lr_number == "29738"
    assert "LAKSHMI COTTAGE" in lr1.party_name
    assert lr1.invoices == ["1250510477"]
    assert lr1.package_count == 3
    assert lr1.weight_kg == 1357.0

    # LR 29740 (with multi-invoice range and delivery party)
    lr3 = sheet.rows[2]
    assert lr3.lr_number == "29740"
    assert "MUTHURAMAN" in lr3.party_name
    assert lr3.invoices == ["1250510479", "1250510480"]
    assert lr3.package_count == 53
    assert lr3.weight_kg == 24050.0
    assert "SIVA BINDING WORKS" in lr3.delivery_to


def test_lr_image_cropper_fr4():
    """Verifies that LRImageCropper generates a valid Base64 PNG crop string (FR4)."""
    # Create a simple synthetic 100x100 white image with black box
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    bbox = [10.0, 10.0, 50.0, 30.0]

    crop_url = LRImageCropper.crop_bounding_box_base64(img, bbox)
    assert crop_url is not None
    assert crop_url.startswith("data:image/png;base64,")

