import os
import pytest
from fastapi.testclient import TestClient

# Ensure test mode settings
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"

from backend.app.main import app  # noqa: E402


def pytest_addoption(parser):
    parser.addoption(
        "--run-slow", action="store_true", default=False, help="run slow tests"
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: mark test as slow to run")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(reason="need --run-slow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Fixture providing a FastAPI TestClient instance."""
    with TestClient(app) as test_client:
        yield test_client

