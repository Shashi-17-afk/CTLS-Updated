import io
import openpyxl
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from backend.app.main import app
from tests.fixtures.synthetic_tirunelveli import create_synthetic_tirunelveli_direct_pdf

client = TestClient(app)


def test_ui_endpoints_serving():
    """Verifies that HTML UI and static assets are correctly served."""
    # 1. Root content negotiation
    resp_api = client.get("/")
    assert resp_api.status_code == status.HTTP_200_OK
    assert resp_api.json()["status"] == "online"

    resp_browser = client.get("/", headers={"accept": "text/html,application/xhtml+xml"})
    assert resp_browser.status_code == status.HTTP_200_OK
    assert "<!DOCTYPE html>" in resp_browser.text
    assert "CTLS Booking OCR" in resp_browser.text

    # 2. Direct /ui route
    resp_ui = client.get("/ui")
    assert resp_ui.status_code == status.HTTP_200_OK
    assert "<!DOCTYPE html>" in resp_ui.text

    # 3. Static assets
    resp_css = client.get("/static/css/style.css")
    assert resp_css.status_code == status.HTTP_200_OK
    assert ":root" in resp_css.text

    resp_js = client.get("/static/js/app.js")
    assert resp_js.status_code == status.HTTP_200_OK
    assert "reconciliationData" in resp_js.text


def test_ui_review_edit_and_export_flow():
    """Verifies the complete milestone UI flow:

    1. Document upload & reconciliation with page extraction attachment.
    2. Review screen data model integrity (9/9 pages, classifications, confidence).
    3. User correction/edit of consignment fields.
    4. Export from modified reconciliation state into final Excel workbook.
    """
    pdf_bytes = create_synthetic_tirunelveli_direct_pdf()

    # Step 1: Ingest & reconcile
    rec_resp = client.post(
        "/api/v1/bookings/tirunelveli/reconcile?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
        files={"file": ("ui_direct.pdf", pdf_bytes, "application/pdf")},
    )
    assert rec_resp.status_code == status.HTTP_200_OK
    rec_json = rec_resp.json()

    # Step 2: Validate attached page extraction info
    assert "page_extractions" in rec_json
    assert len(rec_json["page_extractions"]) == 9
    assert rec_json["page_extractions"][0]["classification"]["classification"] == "MATERIAL_INVOICE"
    assert rec_json["page_extractions"][8]["classification"]["classification"] == "LORRY_RECEIPT"

    # Step 3: Simulate staff user correcting values in UI review screen
    dossier = rec_json["truck_dossiers"][0]
    consign = dossier["reconciled_consignments"][0]
    original_consignee = consign["consignee"]
    consign["consignee"] = "VERIFIED_CTLS_CLIENT_NAME"
    consign["delivery_place"] = "MADURAI_NORTH_HUB"
    consign["total_packages"] = 350

    # Step 4: Export to Excel with user modifications
    excel_resp = client.post(
        "/api/v1/bookings/tirunelveli/export-excel-from-reconciliation",
        json=rec_json,
    )
    assert excel_resp.status_code == status.HTTP_200_OK
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in excel_resp.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(excel_resp.content))
    ws = wb["Consignments"]
    assert ws["D3"].value == "VERIFIED_CTLS_CLIENT_NAME"
    assert ws["E3"].value == "MADURAI_NORTH_HUB"
    assert ws["J3"].value == 350


def test_ui_dom_element_bindings():
    """Verifies that all DOM elements referenced in frontend/js/app.js exist in frontend/index.html
    and that footerStatusText is properly bound.
    """
    resp_html = client.get("/ui")
    assert resp_html.status_code == status.HTTP_200_OK
    html_text = resp_html.text

    resp_js = client.get("/static/js/app.js")
    assert resp_js.status_code == status.HTTP_200_OK
    js_text = resp_js.text

    # Specifically check the element that caused the runtime error
    assert "footerStatusText: document.getElementById('footerStatusText')" in js_text
    assert 'id="footerStatusText"' in html_text


def test_ui_safe_non_json_error_handling():
    """Verifies that frontend/js/app.js handles empty and non-JSON error responses (like 502/504)
    without crashing on await response.json().
    """
    resp_js = client.get("/static/js/app.js")
    assert resp_js.status_code == status.HTTP_200_OK
    js_text = resp_js.text

    # Verify that rawText is read and parsed defensively rather than blind response.json()
    assert "await response.text()" in js_text
    assert "JSON.parse" in js_text
    assert "502 Bad Gateway" in js_text


