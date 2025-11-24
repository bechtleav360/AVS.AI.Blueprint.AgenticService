"""Tests for the REST API routes."""

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    with TestClient(app) as test_client:
        yield test_client


class TestCalculateRoutes:
    """Test suite for calculation routes."""

    def test_calculate_get_add(self, client: TestClient) -> None:
        """Test GET /api/calculate with addition."""
        response = client.get("/api/calculate?a=5&b=3&operation=add")
        assert response.status_code == 200
        data = response.json()
        assert data["result"] == 8
        assert data["error"] is None

    def test_calculate_get_divide(self, client: TestClient) -> None:
        """Test GET /api/calculate with division."""
        response = client.get("/api/calculate?a=20&b=4&operation=divide")
        assert response.status_code == 200
        data = response.json()
        assert data["result"] == 5
        assert data["error"] is None

    def test_calculate_get_divide_by_zero(self, client: TestClient) -> None:
        """Test GET /api/calculate with division by zero."""
        response = client.get("/api/calculate?a=10&b=0&operation=divide")
        assert response.status_code == 200
        data = response.json()
        assert data["error"] == "Division by zero"

    def test_calculate_post_add(self, client: TestClient) -> None:
        """Test POST /api/calculate with addition."""
        response = client.post(
            "/api/calculate",
            json={"a": 5, "b": 3, "operation": "add"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"] == 8
        assert data["error"] is None

    def test_calculate_post_multiply(self, client: TestClient) -> None:
        """Test POST /api/calculate with multiplication."""
        response = client.post(
            "/api/calculate",
            json={"a": 6, "b": 7, "operation": "multiply"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"] == 42
        assert data["error"] is None

    def test_root_endpoint(self, client: TestClient) -> None:
        """Test the root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "REST Microservice"
        assert "documentation" in data
        assert data["documentation"]["swagger_ui"] == "/docs"
        assert data["documentation"]["redoc"] == "/redoc"
        assert data["documentation"]["openapi_json"] == "/openapi.json"

    def test_health_endpoint(self, client: TestClient) -> None:
        """Test the health check endpoint."""
        response = client.get("/health/live")
        assert response.status_code == 200
