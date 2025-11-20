"""Tests for the simple event processor app."""

import pytest
from fastapi.testclient import TestClient

from examples.simple_event_processor.src.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


def test_root_endpoint(client):
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    # Check that response contains expected fields from settings
    assert data["service"] == "Simple Event Processor"
    assert data["version"] == "0.1.0"
    assert "description" in data


def test_health_endpoint(client):
    """Test the health check endpoint."""
    response = client.get("/health/live")
    assert response.status_code == 200
