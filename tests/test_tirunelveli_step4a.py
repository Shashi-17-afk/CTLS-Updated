from fastapi import status
from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from backend.app.schemas.classification import (
    BookingType,
    LoadingPoint,
    PageClassificationType,
)
from backend.app.services.classification.classifier import TirunelveliPageClassifier
from backend.app.services.extraction.tirunelveli.lr_normalizer import LRNormalizer
from tests.fixtures.synthetic_tirunelveli import (
    create_synthetic_ambiguous_page_pdf,
    create_synthetic_tirunelveli_direct_pdf,
    create_synthetic_tirunelveli_group_pdf,
)

client = TestClient(app, raise_server_exceptions=False)


def test_mandatory_input_validation():
    """Validates that loading_point and booking_type are strictly mandatory with HTTP 422 on failure."""
    pdf_bytes = create_synthetic_tirunelveli_direct_pdf()

    # 1. Missing both parameters -> 422
    resp = client.post(
        "/api/v1/bookings/tirunelveli/extract",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 2. Missing booking_type -> 422
    resp = client.post(
        "/api/v1/bookings/tirunelveli/extract?loading_point=tirunelveli",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 3. Invalid loading point -> 422
    resp = client.post(
        "/api/v1/bookings/tirunelveli/extract?loading_point=delhi&booking_type=direct",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 4. Erode requested on Tirunelveli milestone -> 422 with explanation
    resp = client.post(
        "/api/v1/bookings/tirunelveli/extract?loading_point=erode&booking_type=direct",
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "erode" in resp.json()["message"].lower()


def test_lr_normalization_utility():
    """Tests LR normalization preserving both raw string and normalized cross-referencing value."""
    # Test leading zeros preserved in raw, stripped in normalized
    lr_item = LRNormalizer.normalize(raw_text="019427", source_page=1)
    assert lr_item.raw_value == "019427"
    assert lr_item.normalized_value == "19427"
    assert not lr_item.is_ambiguous

    # Test matching cross-reference
    lr_item_plain = LRNormalizer.normalize(raw_text="19427", source_page=2)
    assert LRNormalizer.match(lr_item, lr_item_plain) is True

    # Test ambiguous short LR
    lr_short = LRNormalizer.normalize(raw_text="42", source_page=3)
    assert lr_short.is_ambiguous is True
    assert "Suspiciously short" in lr_short.flag_reason


def test_kunnamkulam_direct_booking_classification_and_extraction():
    """Tests 9-page Kunnamkulam Direct Booking (PRD §6.3): 4 invoices, 4 EWBs, 1 LR."""
    pdf_bytes = create_synthetic_tirunelveli_direct_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/extract?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("Sl.no.5_TN52Y7426_Kunnamkulam_22.06.25.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["loading_point"] == "tirunelveli"
    assert data["booking_type"] == "direct"
    assert data["page_count"] == 9
    assert len(data["pages"]) == 9  # Zero pages dropped

    # Pages 1 to 4: Material Invoices
    expected_inv_numbers = ["2250601397", "2250601398", "2250601399", "2250601400"]
    for i in range(4):
        p = data["pages"][i]
        assert p["classification"]["classification"] == PageClassificationType.MATERIAL_INVOICE.value
        inv = p["invoice_data"]
        assert inv is not None
        assert inv["invoice_number"]["value"] == expected_inv_numbers[i]
        assert inv["printed_lr_number"]["raw_value"] == "019427"
        assert inv["printed_lr_number"]["normalized_value"] == "19427"
        assert inv["freight_amount"]["value"] == 0.0  # Party freight

    # Pages 5 to 8: E-Way Bills
    expected_ewbs = ["591834108616", "561834108617", "561834108620", "501834108622"]
    for i in range(4):
        p = data["pages"][4 + i]
        assert p["classification"]["classification"] == PageClassificationType.EWAY_BILL.value
        ewb = p["eway_data"]
        assert ewb is not None
        assert ewb["eway_bill_number"]["value"] == expected_ewbs[i]
        assert ewb["valid_upto"]["value"] == "24/06/2025"
        assert ewb["transporter_doc_no"]["normalized_value"] == "19427"

    # Page 9: Lorry Receipt (LR)
    lr_page = data["pages"][8]
    assert lr_page["classification"]["classification"] == PageClassificationType.LORRY_RECEIPT.value
    lr = lr_page["lr_data"]
    assert lr is not None
    assert lr["lr_number"]["raw_value"] == "019427"
    assert lr["lr_number"]["normalized_value"] == "19427"
    assert lr["truck_number"]["value"] == "TN52Y7426"
    assert lr["delivery_place"]["value"] == "Kunnamkulam"
    assert lr["weight_kg"]["value"] == 17450.60
    assert lr["preprinted_freight_ignored"] is True


def test_trichy_group_booking_classification_and_extraction():
    """Tests 14-page Trichy Group Booking (PRD §6.4): 5 invoices, 5 EWBs, 1 Security Copy, 3 LRs."""
    pdf_bytes = create_synthetic_tirunelveli_group_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/extract?loading_point=tirunelveli&booking_type=group&enable_ocr=false",
        files={"file": ("TN30BD2189_Trichy_20.06.2025.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["page_count"] == 14
    assert len(data["pages"]) == 14

    # Pages 1 to 5: Material Invoices with freight amounts
    for i in range(5):
        p = data["pages"][i]
        assert p["classification"]["classification"] == PageClassificationType.MATERIAL_INVOICE.value
        assert p["invoice_data"]["freight_amount"]["value"] > 0.0  # Shipper freight

    # Page 11: Security Copy
    sec_page = data["pages"][10]
    assert sec_page["classification"]["classification"] == PageClassificationType.SECURITY_COPY.value
    sec = sec_page["security_data"]
    assert sec is not None
    assert sec["lorry_number"]["value"] == "TN30BD2189"
    assert sec["total_packages"]["value"] == 272
    assert sec["total_net_weight_kg"]["value"] == 15993.60
    assert sec["total_value_rs"]["value"] == 1302407.0

    # Pages 12 to 14: 3 LRs
    expected_lrs = ["019406", "019407", "019408"]
    for i, expected_lr in enumerate(expected_lrs):
        p = data["pages"][11 + i]
        assert p["classification"]["classification"] == PageClassificationType.LORRY_RECEIPT.value
        assert p["lr_data"]["lr_number"]["raw_value"] == expected_lr


def test_ambiguous_page_flagged_as_unknown():
    """Tests that an unclassifiable document is marked as UNKNOWN_PAGE without being dropped."""
    pdf_bytes = create_synthetic_ambiguous_page_pdf()

    resp = client.post(
        "/api/v1/bookings/tirunelveli/extract?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("cafeteria_menu.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["page_count"] == 1
    page = data["pages"][0]
    assert page["classification"]["classification"] == PageClassificationType.UNKNOWN_PAGE.value
    assert page["classification"]["is_ambiguous"] is True
    assert len(page["review_flags"]) > 0
    assert any("manual classification" in flag.lower() for flag in data["global_review_flags"])


def test_eway_bill_expiry_extraction_never_substitutes_doc_date():
    """Regression test: EWB expiry strictly extracts Valid Until/Valid Upto with date and optional time,

    and never substitutes earlier Document Date or Generated Date.
    """
    from backend.app.services.extraction.tirunelveli.eway_extractor import EwayBillExtractor

    # Case 1: Scanned bundle format with date & time and earlier generated/document dates
    raw_ocr_text = """
    e-Way Bill System
    Government of India
    e-Way Bill No: 331084729101
    Generated Date: 22/06/2025 09:35
    Document Date: 22/06/2025
    Valid From: 22/06/2025 09:35
    Valid Until: 23/06/202523:59
    Transporter Doc. No.: 19427
    Vehicle No: TN52Y7426
    """
    ewb_data = EwayBillExtractor.extract(raw_ocr_text, page_number=5)
    assert ewb_data.valid_upto is not None
    assert ewb_data.valid_upto.value == "23/06/2025 23:59"
    assert ewb_data.valid_upto.value != "22/06/2025"

    # Case 2: Standard date-only format
    text_date_only = """
    e-Way Bill No: 331084729102
    Doc Date: 22/06/2025
    Valid Upto: 24/06/2025
    """
    ewb_data2 = EwayBillExtractor.extract(text_date_only, page_number=6)
    assert ewb_data2.valid_upto is not None
    assert ewb_data2.valid_upto.value == "24/06/2025"

    # Case 3: Missing Valid Upto should return None, NEVER guess doc date
    text_no_expiry = """
    e-Way Bill No: 331084729103
    Document Date: 22/06/2025
    """
    ewb_data3 = EwayBillExtractor.extract(text_no_expiry, page_number=7)
    assert ewb_data3.valid_upto is None


def test_party_name_normalizer_spacing():
    """Regression test: PartyNameNormalizer restores spaces to collapsed words

    without affecting numbers or already formatted text.
    """
    from backend.app.services.extraction.tirunelveli.party_normalizer import PartyNameNormalizer

    assert PartyNameNormalizer.normalize("SRIMEENAKSHIPAPERMART") == "SRI MEENAKSHI PAPER MART"
    assert PartyNameNormalizer.normalize("SRI MEENAKSHIPAPER MART") == "SRI MEENAKSHI PAPER MART"
    assert PartyNameNormalizer.normalize("KAUSIKAENTERPRISES") == "KAUSIKA ENTERPRISES"
    assert PartyNameNormalizer.normalize("MADURAI,TAMILNADU") == "MADURAI, TAMILNADU"
    assert PartyNameNormalizer.normalize("Kausika Enterprises Private Limited, Ernakulam") == "Kausika Enterprises Private Limited, Ernakulam"

