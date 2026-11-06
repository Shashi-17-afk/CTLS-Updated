import io
import os
from fastapi import status
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from tests.helpers import (
    create_encrypted_pdf,
    create_mixed_pdf,
    create_scanned_pdf,
    create_synthetic_image,
    create_text_pdf,
)


def test_text_based_pdf_ingestion(client: TestClient) -> None:
    """Verify text-based PDF extracts embedded text successfully."""
    pdf_bytes = create_text_pdf(text="Logistics Tax Invoice INV-9001\nTotal Freight: 12000 INR", pages=1)
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("invoice_test.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["file_type"] == "pdf"
    assert data["page_count"] == 1
    assert data["overall_status"] == "TEXT_EXTRACTED"
    assert len(data["pages"]) == 1

    page = data["pages"][0]
    assert page["status"] == "TEXT_EXTRACTED"
    assert page["has_embedded_text"] is True
    assert page["is_scanned"] is False
    assert "INV-9001" in page["extracted_text"]
    assert page["char_count"] > 0
    assert page["word_count"] > 0


def test_scanned_pdf_returns_ocr_required(client: TestClient) -> None:
    """Verify scanned PDF returns explicit OCR_REQUIRED status when OCR is disabled."""
    pdf_bytes = create_scanned_pdf(pages=1)
    response = client.post(
        "/api/v1/documents/ingest?enable_ocr=false",
        files={"file": ("scanned_lr.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["file_type"] == "pdf"
    assert data["page_count"] == 1
    assert data["overall_status"] == "OCR_REQUIRED"

    page = data["pages"][0]
    assert page["status"] == "OCR_REQUIRED"
    assert page["has_embedded_text"] is False
    assert page["is_scanned"] is True
    assert page["extracted_text"] is None


def test_mixed_pdf_ingestion(client: TestClient) -> None:
    """Verify mixed PDF (Page 1 text, Page 2 scan) returns MIXED_CONTENT when OCR is disabled."""
    pdf_bytes = create_mixed_pdf()
    response = client.post(
        "/api/v1/documents/ingest?enable_ocr=false",
        files={"file": ("mixed_document.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["page_count"] == 2
    assert data["overall_status"] == "MIXED_CONTENT"

    p1 = data["pages"][0]
    assert p1["page_number"] == 1
    assert p1["status"] == "TEXT_EXTRACTED"
    assert p1["has_embedded_text"] is True
    assert "LORRY RECEIPT" in p1["extracted_text"]

    p2 = data["pages"][1]
    assert p2["page_number"] == 2
    assert p2["status"] == "OCR_REQUIRED"
    assert p2["has_embedded_text"] is False
    assert p2["is_scanned"] is True
    assert p2["extracted_text"] is None


def test_valid_image_ingestion_png_and_jpeg(client: TestClient) -> None:
    """Verify valid PNG and JPEG images are decoded and marked as VALIDATED_IMAGE when OCR is disabled."""
    # Test PNG
    png_bytes = create_synthetic_image("PNG", 200, 200)
    resp_png = client.post(
        "/api/v1/documents/ingest?enable_ocr=false",
        files={"file": ("photo_lr.png", png_bytes, "image/png")},
    )
    assert resp_png.status_code == status.HTTP_200_OK
    png_data = resp_png.json()
    assert png_data["file_type"] == "png"
    assert png_data["overall_status"] == "VALIDATED_IMAGE"
    assert png_data["pages"][0]["status"] == "OCR_REQUIRED"

    # Test JPEG
    jpeg_bytes = create_synthetic_image("JPEG", 200, 200)
    resp_jpeg = client.post(
        "/api/v1/documents/ingest?enable_ocr=false",
        files={"file": ("photo_invoice.jpg", jpeg_bytes, "image/jpeg")},
    )
    assert resp_jpeg.status_code == status.HTTP_200_OK
    jpeg_data = resp_jpeg.json()
    assert jpeg_data["file_type"] == "jpeg"
    assert jpeg_data["overall_status"] == "VALIDATED_IMAGE"


def test_unsupported_file_disguised_extension(client: TestClient) -> None:
    """Verify executable or plain-text bytes disguised as a PDF are rejected based on magic bytes."""
    fake_content = b"Plain text file claiming to be a PDF invoice for testing."
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("fake_invoice.pdf", fake_content, "application/pdf")},
    )
    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    data = response.json()
    assert data["error_code"] == "HTTP_415"


def test_empty_file_rejected(client: TestClient) -> None:
    """Verify empty or near-empty files are rejected with HTTP 400."""
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_encrypted_pdf_rejected(client: TestClient) -> None:
    """Verify password-protected PDFs are rejected safely with HTTP 422."""
    encrypted_bytes = create_encrypted_pdf("secretpass")
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("locked_invoice.pdf", encrypted_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    data = response.json()
    assert "encrypted" in data["message"].lower() or "password" in data["message"].lower()


def test_malformed_pdf_rejected(client: TestClient) -> None:
    """Verify corrupted PDF bytes are rejected safely without crashing the server."""
    corrupted_bytes = b"%PDF-1.7\nCorrupted binary junk payload that terminates abruptly\x00\xff"
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("broken.pdf", corrupted_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    data = response.json()
    assert "corrupt" in data["message"].lower() or "unable" in data["message"].lower() or "malformed" in data["message"].lower()


def test_excessive_page_count_rejected(client: TestClient, monkeypatch) -> None:
    """Verify PDFs exceeding MAX_PDF_PAGES are rejected."""
    # Temporarily lower MAX_PDF_PAGES to 3 for fast testing
    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 3)
    four_page_pdf = create_text_pdf("Page content", pages=4)
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("long_document.pdf", four_page_pdf, "application/pdf")},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    data = response.json()
    assert "exceeds maximum page limit" in data["message"]


def test_oversized_file_rejected(client: TestClient, monkeypatch) -> None:
    """Verify files exceeding MAX_FILE_SIZE_BYTES are rejected with HTTP 413."""
    # Temporarily lower MAX_FILE_SIZE_BYTES to 1 KB for test
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_BYTES", 1024)
    oversized_data = b"%PDF-1.4\n" + (b"X" * 2000)
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("huge_file.pdf", oversized_data, "application/pdf")},
    )
    assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE


def test_in_memory_processing_leaves_no_lingering_temp_files(client: TestClient) -> None:
    """Verify that processing files leaves no persistent temporary files on disk."""
    before_files = set(os.listdir("."))
    pdf_bytes = create_text_pdf("Temporary Test Invoice", pages=1)
    response = client.post(
        "/api/v1/documents/ingest",
        files={"file": ("clean_test.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == status.HTTP_200_OK
    after_files = set(os.listdir("."))

    # No new file or folder (e.g. temp, uploads) should linger in root
    diff = after_files - before_files
    assert len(diff) == 0
