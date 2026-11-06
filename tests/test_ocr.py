import numpy as np
from PIL import Image, ImageDraw
from fastapi import status
from fastapi.testclient import TestClient

from backend.app.services.ocr.base import BaseOCREngine
from backend.app.services.ocr.engine_mock import MockOCREngine
from backend.app.services.ocr.factory import reset_ocr_engine, set_ocr_engine
from backend.app.services.ocr.preprocessor import ImagePreprocessor
from tests.helpers import (
    create_mixed_pdf_with_scanned_text,
    create_scanned_pdf,
    create_scanned_pdf_with_text,
    create_synthetic_image_with_text,
    create_text_pdf,
)


def test_ocr_scanned_pdf_extracts_text(client: TestClient) -> None:
    """Verify local OCR runs on a scanned PDF and returns text, confidence, and bounding boxes."""
    reset_ocr_engine()
    pdf_bytes = create_scanned_pdf_with_text("SCANNED INVOICE INV-5544\nTOTAL 18500 INR")
    response = client.post(
        "/api/v1/documents/ingest?enable_ocr=true",
        files={"file": ("scanned_invoice.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["file_type"] == "pdf"
    assert data["page_count"] == 1
    assert data["overall_status"] == "TEXT_EXTRACTED"

    page = data["pages"][0]
    assert page["status"] == "TEXT_EXTRACTED"
    assert page["has_embedded_text"] is False
    assert page["is_scanned"] is True
    assert page["extraction_method"] == "OCR"
    assert "INV-5544" in page["extracted_text"] or "18500" in page["extracted_text"]
    assert page["ocr_confidence"] is not None
    assert 0.0 <= page["ocr_confidence"] <= 1.0
    assert len(page["bounding_boxes"]) > 0

    box = page["bounding_boxes"][0]
    assert "text" in box
    assert "confidence" in box
    assert len(box["box"]) == 4  # 4-point polygon


def test_ocr_standalone_image_extracts_text(client: TestClient) -> None:
    """Verify local OCR processes standalone PNG/JPEG images."""
    reset_ocr_engine()
    img_bytes = create_synthetic_image_with_text("LORRY RECEIPT LR-7711\nFREIGHT 32000 INR")
    response = client.post(
        "/api/v1/documents/ingest?enable_ocr=true",
        files={"file": ("lr_photo.png", img_bytes, "image/png")},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["file_type"] == "png"
    assert data["overall_status"] == "TEXT_EXTRACTED"

    page = data["pages"][0]
    assert page["status"] == "TEXT_EXTRACTED"
    assert page["extraction_method"] == "OCR"
    assert "LR-7711" in page["extracted_text"] or "32000" in page["extracted_text"]
    assert page["ocr_confidence"] is not None
    assert len(page["bounding_boxes"]) > 0


def test_ocr_mixed_pdf_extracts_both_embedded_and_ocr(client: TestClient) -> None:
    """
    Verify mixed PDF:
    Page 1 uses embedded text extraction (ocr_confidence is None).
    Page 2 uses OCR (ocr_confidence is float).
    """
    reset_ocr_engine()
    pdf_bytes = create_mixed_pdf_with_scanned_text()
    response = client.post(
        "/api/v1/documents/ingest?enable_ocr=true",
        files={"file": ("mixed_tax_and_lr.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["page_count"] == 2
    assert data["overall_status"] == "TEXT_EXTRACTED"

    # Page 1: Native text
    p1 = data["pages"][0]
    assert p1["page_number"] == 1
    assert p1["extraction_method"] == "EMBEDDED_TEXT"
    assert p1["has_embedded_text"] is True
    assert p1["ocr_confidence"] is None  # Honest signal: not fabricated!
    assert "DIGITAL TAX INVOICE" in p1["extracted_text"]

    # Page 2: OCR
    p2 = data["pages"][1]
    assert p2["page_number"] == 2
    assert p2["extraction_method"] == "OCR"
    assert p2["is_scanned"] is True
    assert p2["ocr_confidence"] is not None
    assert "BILTY" in p2["extracted_text"] or "LR-9002" in p2["extracted_text"] or "ATTACHED" in p2["extracted_text"]


def test_ocr_empty_scan_returns_empty_page(client: TestClient) -> None:
    """Verify completely blank scanned image returns EMPTY_PAGE when OCR detects no text."""
    reset_ocr_engine()
    pdf_bytes = create_scanned_pdf(pages=1)
    response = client.post(
        "/api/v1/documents/ingest?enable_ocr=true",
        files={"file": ("blank_scan.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    page = data["pages"][0]
    assert page["status"] == "EMPTY_PAGE"
    assert page["extracted_text"] is None
    assert page["extraction_method"] == "OCR"


def test_mock_ocr_engine_injection(client: TestClient) -> None:
    """Verify pluggable OCR architecture allows deterministic mock engine injection."""
    mock = MockOCREngine(mock_text="DETERMINISTIC MOCK INVOICE 999", mock_confidence=0.9876)
    set_ocr_engine(mock)

    try:
        pdf_bytes = create_scanned_pdf(pages=1)
        response = client.post(
            "/api/v1/documents/ingest?enable_ocr=true",
            files={"file": ("test_mock.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        page = data["pages"][0]
        assert page["status"] == "TEXT_EXTRACTED"
        assert page["extracted_text"] == "DETERMINISTIC MOCK INVOICE 999"
        assert page["ocr_confidence"] == 0.9876
    finally:
        reset_ocr_engine()


def test_ocr_engine_failure_handled_safely(client: TestClient) -> None:
    """Verify OCR engine exception is caught gracefully and returns PROCESSING_FAILED."""
    failing_mock = MockOCREngine(fail=True)
    set_ocr_engine(failing_mock)

    try:
        pdf_bytes = create_scanned_pdf(pages=1)
        response = client.post(
            "/api/v1/documents/ingest?enable_ocr=true",
            files={"file": ("fail_ocr.pdf", pdf_bytes, "application/pdf")},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        page = data["pages"][0]
        assert page["status"] == "PROCESSING_FAILED"
        assert "OCR execution failed" in page["error_message"]
        # Ensure internal stack trace is not leaked in the JSON
        assert "Traceback" not in response.text
    finally:
        reset_ocr_engine()


def test_image_preprocessor_deskew() -> None:
    """Verify ImagePreprocessor detects skew and performs rotation."""
    # Create image with horizontal text and rotate it by 5 degrees
    img = Image.new("RGB", (400, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((50, 90), "HORIZONTAL TEXT LINE TO MEASURE SKEW ANGLE", fill=(0, 0, 0))
    rotated_img = img.rotate(5, expand=True, fillcolor=(255, 255, 255))

    preprocessed, detected_angle = ImagePreprocessor.preprocess(rotated_img)
    assert isinstance(preprocessed, np.ndarray)
    assert abs(detected_angle) > 0.0
