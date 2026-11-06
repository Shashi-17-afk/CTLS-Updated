from fastapi import status
from fastapi.testclient import TestClient


def test_404_error_response_format(client: TestClient) -> None:
    """Verify 404 responses conform to the safe ErrorResponse schema."""
    response = client.get("/api/v1/nonexistent-route")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert data["error_code"] == "HTTP_404"
    assert "message" in data
    assert "timestamp" in data
    # Ensure no internal stack trace or raw server details leaked
    assert "traceback" not in data


def test_internal_server_error_safety() -> None:
    """Verify unhandled exceptions return generic 500 without leaking stack traces."""
    from backend.app.main import app

    @app.get("/test-internal-crash", include_in_schema=False)
    def crash_endpoint() -> None:
        raise RuntimeError("Sensitive internal database connection string failed: secret_user:secret_pass")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/test-internal-crash")
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    data = response.json()
    assert data["error_code"] == "INTERNAL_SERVER_ERROR"
    assert "An unexpected internal error occurred" in data["message"]
    # Verify sensitive error string was NOT leaked to the client
    assert "secret_pass" not in response.text
    assert "RuntimeError" not in response.text


def test_memory_error_structured_503() -> None:
    """Verify MemoryError returns structured JSON 503 instead of unstructured crash."""
    from unittest.mock import patch
    from backend.app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    with patch("backend.app.services.extraction.tirunelveli.service.TirunelveliExtractionService.process", side_effect=MemoryError("Out of memory")):
        response = client.post(
            "/api/v1/bookings/tirunelveli/reconcile?loading_point=tirunelveli&booking_type=direct&enable_ocr=false",
            files={"file": ("dummy.pdf", b"%PDF-1.4 dummy", "application/pdf")},
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        assert data["error_code"] == "HTTP_503"
        assert "memory limit exceeded" in data["message"].lower()

