import os
import pytest
from fastapi.testclient import TestClient

# Ensure test mode settings
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"

from backend.app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Fixture providing a FastAPI TestClient instance."""
    with TestClient(app) as test_client:
        yield test_client
