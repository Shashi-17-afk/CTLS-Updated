import io
from PIL import Image, ImageDraw
import pymupdf


def create_text_pdf(
    text: str = "Logistics Tax Invoice INV-2026-9081\nDate: 2026-10-27\nTotal Freight: 45000.00 INR\nConsignor: Global Logistics Ltd",
    pages: int = 1,
) -> bytes:
    """Generates an in-memory synthetic PDF with embedded text."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text(pymupdf.Point(50, 72), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_scanned_pdf(pages: int = 1) -> bytes:
    """Generates an in-memory synthetic PDF containing a full-page blank raster image (no text layer)."""
    img = Image.new("RGB", (600, 800), color=(240, 240, 240))
    img_buf = io.BytesIO()
    img.save(img_buf, format="JPEG")
    img_bytes = img_buf.getvalue()

    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=img_bytes)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_scanned_pdf_with_text(
    text: str = "SCANNED INVOICE INV-5544\nTOTAL AMOUNT 18500 INR\nVEHICLE KA-01-EE-2233",
    pages: int = 1,
) -> bytes:
    """Generates an in-memory synthetic PDF with visual raster text but NO PDF text layer."""
    img = Image.new("RGB", (800, 1100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = 50
    for line in text.splitlines():
        draw.text((60, y), line, fill=(0, 0, 0))
        y += 40

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=img_bytes)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_mixed_pdf() -> bytes:
    """Generates a 2-page PDF: Page 1 with embedded text, Page 2 with a blank scanned raster image."""
    img = Image.new("RGB", (600, 800), color=(235, 235, 235))
    img_buf = io.BytesIO()
    img.save(img_buf, format="JPEG")
    img_bytes = img_buf.getvalue()

    doc = pymupdf.open()
    # Page 1: Text-based
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text(
        pymupdf.Point(50, 72),
        "LORRY RECEIPT / BILTY\nLR No: LR-883921\nVehicle No: MH-12-PQ-9988\nFrom: Mumbai To: Delhi",
        fontsize=12,
    )
    # Page 2: Blank scanned image
    p2 = doc.new_page(width=595, height=842)
    p2.insert_image(p2.rect, stream=img_bytes)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_mixed_pdf_with_scanned_text() -> bytes:
    """Generates a 2-page PDF: Page 1 with embedded text, Page 2 with visual raster text for OCR."""
    doc = pymupdf.open()
    # Page 1: Native text
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text(
        pymupdf.Point(50, 72),
        "DIGITAL TAX INVOICE INV-1001\nCONSIGNOR ALPHA LOGISTICS\nTOTAL 50000",
        fontsize=12,
    )
    # Page 2: Scanned raster image with visible text
    img = Image.new("RGB", (800, 1100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((60, 60), "ATTACHED SCANNED BILTY LR-9002", fill=(0, 0, 0))
    draw.text((60, 120), "DESTINATION HYDERABAD", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    p2 = doc.new_page(width=595, height=842)
    p2.insert_image(p2.rect, stream=buf.getvalue())

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def create_encrypted_pdf(password: str = "confidential123") -> bytes:
    """Generates a password-protected PDF to test encryption rejection."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text(pymupdf.Point(50, 72), "Encrypted Confidential Document", fontsize=12)
    pdf_bytes = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw=password,
        owner_pw=password,
    )
    doc.close()
    return pdf_bytes


def create_synthetic_image(fmt: str = "PNG", width: int = 300, height: int = 300) -> bytes:
    """Generates a blank standalone image in memory."""
    img = Image.new("RGB", (width, height), color=(245, 245, 245))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def create_synthetic_image_with_text(
    text: str = "LORRY RECEIPT LR-7711\nFREIGHT 32000 INR",
    fmt: str = "PNG",
    width: int = 500,
    height: int = 200,
) -> bytes:
    """Generates a standalone image with visible text for OCR testing."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = 30
    for line in text.splitlines():
        draw.text((30, y), line, fill=(0, 0, 0))
        y += 40
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()
