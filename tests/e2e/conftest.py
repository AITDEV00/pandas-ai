"""
Shared fixtures for e2e tests.

This conftest provides a server readiness check that runs once before
all e2e tests to ensure the local server is reachable.
"""

import os

import httpx
import pytest

BASE_URL = os.environ.get("TEST_SERVER_URL", "http://localhost:8000")


def pytest_collection_modifyitems(config, items):
    """Add e2e marker to all tests in this directory."""
    for item in items:
        if "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)


def pytest_configure(config):
    """Register the e2e marker."""
    config.addinivalue_line("markers", "e2e: end-to-end test requiring a running server")


@pytest.fixture(scope="session", autouse=True)
def verify_server_running():
    """Ensure the server is reachable before running any e2e tests."""
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=10)
        assert resp.status_code == 200, f"Server returned {resp.status_code}"
    except httpx.ConnectError:
        pytest.exit(
            f"\n❌ Server not reachable at {BASE_URL}\n"
            f"   Start it with: make -f Makefile.build run-local\n"
        )
