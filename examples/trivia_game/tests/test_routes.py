"""Tests for the trivia game API routes."""

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


class TestTriviaGameRoutes:
    """Test suite for trivia game routes."""

    def test_root_endpoint(self, client: TestClient) -> None:
        """Test the root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Trivia Game"

    def test_start_game(self, client: TestClient) -> None:
        """Test starting a new game."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_health_endpoint(self, client: TestClient) -> None:
        """Test the health check endpoint."""
        response = client.get("/health/live")
        assert response.status_code == 200
