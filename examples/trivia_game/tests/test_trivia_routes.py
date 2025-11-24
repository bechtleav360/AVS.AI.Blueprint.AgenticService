"""Tests for the trivia game API routes."""

import pytest
from fastapi.testclient import TestClient

from examples.trivia_game.src.main import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    with TestClient(app) as test_client:
        yield test_client


class TestTriviaGameRoutes:
    """Test suite for trivia game routes."""

    def test_root_endpoint(self, client: TestClient) -> None:
        """Test the root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Trivia Game"
        assert "version" in data
        assert "description" in data

    def test_start_game(self, client: TestClient) -> None:
        """Test starting a new game with medium difficulty."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 3},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_start_game_easy_difficulty(self, client: TestClient) -> None:
        """Test starting a game with easy difficulty."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "easy", "num_questions": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_start_game_hard_difficulty(self, client: TestClient) -> None:
        """Test starting a game with hard difficulty."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "hard", "num_questions": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_start_game_custom_questions(self, client: TestClient) -> None:
        """Test starting a game with custom number of questions."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_health_endpoint(self, client: TestClient) -> None:
        """Test the health check endpoint."""
        response = client.get("/health/live")
        assert response.status_code == 200

    def test_health_ready_endpoint(self, client: TestClient) -> None:
        """Test the readiness check endpoint."""
        response = client.get("/health/ready")
        assert response.status_code == 200

    def test_start_game_missing_difficulty(self, client: TestClient) -> None:
        """Test starting a game without difficulty parameter."""
        response = client.post(
            "/api/game/start",
            json={"num_questions": 3},
        )
        # Should either use default or return validation error
        assert response.status_code in [200, 422]

    def test_start_game_missing_num_questions(self, client: TestClient) -> None:
        """Test starting a game without num_questions parameter."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "medium"},
        )
        # Should either use default or return validation error
        assert response.status_code in [200, 422]

    def test_start_game_returns_game_id(self, client: TestClient) -> None:
        """Test that starting a game returns a unique game_id."""
        response1 = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 3},
        )
        response2 = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 3},
        )
        assert response1.status_code == 200
        assert response2.status_code == 200
        data1 = response1.json()
        data2 = response2.json()
        # Each game should have a unique ID
        assert data1["game_id"] != data2["game_id"]
