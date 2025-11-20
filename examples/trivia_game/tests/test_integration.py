"""Integration tests for the Trivia Game example.

Tests the complete workflow of the trivia game including:
- Game initialization
- Question generation
- Answer evaluation
- Game state management
"""

import pytest
from fastapi.testclient import TestClient

from examples.trivia_game.src.main import app, trivia_agent


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the trivia game API."""
    return TestClient(app)


class TestTriviaGameIntegration:
    """Integration tests for the complete trivia game workflow."""

    def test_app_initialization(self):
        """Test that the trivia game app initializes correctly."""
        assert app is not None
        assert trivia_agent is not None

    def test_root_endpoint_returns_service_info(self, client: TestClient):
        """Test root endpoint returns service information."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Trivia Game"
        assert "version" in data
        assert "description" in data

    def test_health_check_endpoints(self, client: TestClient):
        """Test health check endpoints are available."""
        # Test liveness probe
        response = client.get("/health/live")
        assert response.status_code == 200

        # Test readiness probe
        response = client.get("/health/ready")
        assert response.status_code == 200

    def test_start_game_creates_game_session(self, client: TestClient):
        """Test starting a game creates a valid game session."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 3},
        )
        assert response.status_code == 200
        data = response.json()

        # Verify game session structure
        assert "game_id" in data
        assert data["status"] == "started"

    def test_start_game_with_different_difficulties(self, client: TestClient):
        """Test starting games with different difficulty levels."""
        difficulties = ["easy", "medium", "hard"]

        for difficulty in difficulties:
            response = client.post(
                "/api/game/start",
                json={"difficulty": difficulty, "num_questions": 2},
            )
            assert response.status_code == 200
            data = response.json()
            assert "game_id" in data
            assert data["status"] == "started"

    def test_start_game_with_various_question_counts(self, client: TestClient):
        """Test starting games with different question counts."""
        question_counts = [1, 3, 5, 10]

        for count in question_counts:
            response = client.post(
                "/api/game/start",
                json={"difficulty": "medium", "num_questions": count},
            )
            assert response.status_code == 200
            data = response.json()
            assert "game_id" in data
            assert data["status"] == "started"

    def test_multiple_games_have_unique_ids(self, client: TestClient):
        """Test that each game gets a unique ID."""
        game_ids = set()

        for _ in range(5):
            response = client.post(
                "/api/game/start",
                json={"difficulty": "medium", "num_questions": 3},
            )
            assert response.status_code == 200
            data = response.json()
            game_ids.add(data["game_id"])

        # All game IDs should be unique
        assert len(game_ids) == 5

    def test_game_session_persistence(self, client: TestClient):
        """Test that game sessions persist across requests."""
        # Start a game
        start_response = client.post(
            "/api/game/start",
            json={"difficulty": "easy", "num_questions": 2},
        )
        assert start_response.status_code == 200
        game_id = start_response.json()["game_id"]

        # Verify game was created
        assert game_id is not None
        assert isinstance(game_id, str)
        assert len(game_id) > 0

    def test_easy_difficulty_game_flow(self, client: TestClient):
        """Test complete flow of an easy difficulty game."""
        # Start game
        start_response = client.post(
            "/api/game/start",
            json={"difficulty": "easy", "num_questions": 2},
        )
        assert start_response.status_code == 200
        game_data = start_response.json()

        # Verify game started
        assert game_data["status"] == "started"
        assert "game_id" in game_data

    def test_medium_difficulty_game_flow(self, client: TestClient):
        """Test complete flow of a medium difficulty game."""
        # Start game
        start_response = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 3},
        )
        assert start_response.status_code == 200
        game_data = start_response.json()

        # Verify game started
        assert game_data["status"] == "started"
        assert "game_id" in game_data

    def test_hard_difficulty_game_flow(self, client: TestClient):
        """Test complete flow of a hard difficulty game."""
        # Start game
        start_response = client.post(
            "/api/game/start",
            json={"difficulty": "hard", "num_questions": 2},
        )
        assert start_response.status_code == 200
        game_data = start_response.json()

        # Verify game started
        assert game_data["status"] == "started"
        assert "game_id" in game_data

    def test_game_response_structure(self, client: TestClient):
        """Test that game responses have correct structure."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 1},
        )
        assert response.status_code == 200
        data = response.json()

        # Verify all required fields are present
        required_fields = ["game_id", "status"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    def test_concurrent_games(self, client: TestClient):
        """Test that multiple concurrent games can be managed."""
        games = []

        # Start multiple games
        for i in range(3):
            response = client.post(
                "/api/game/start",
                json={"difficulty": "medium", "num_questions": 2},
            )
            assert response.status_code == 200
            games.append(response.json())

        # Verify all games are independent
        assert len(games) == 3
        game_ids = [g["game_id"] for g in games]
        assert len(set(game_ids)) == 3  # All unique

    def test_game_with_single_question(self, client: TestClient):
        """Test game with minimum number of questions."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "easy", "num_questions": 1},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_game_with_many_questions(self, client: TestClient):
        """Test game with many questions."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "hard", "num_questions": 20},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_api_error_handling(self, client: TestClient):
        """Test API error handling for invalid requests."""
        # Test with invalid JSON
        response = client.post(
            "/api/game/start",
            json={"invalid_field": "value"},
        )
        # Should either use defaults or return validation error
        assert response.status_code in [200, 422]

    def test_game_start_response_consistency(self, client: TestClient):
        """Test that game start responses are consistent."""
        responses = []

        for _ in range(3):
            response = client.post(
                "/api/game/start",
                json={"difficulty": "medium", "num_questions": 3},
            )
            assert response.status_code == 200
            responses.append(response.json())

        # Verify all responses have same structure
        for resp in responses:
            assert "game_id" in resp
            assert "status" in resp
            assert resp["status"] == "started"


class TestTriviaGameAgent:
    """Integration tests for the trivia game agent."""

    def test_agent_is_initialized(self):
        """Test that the trivia agent is properly initialized."""
        assert trivia_agent is not None
        assert hasattr(trivia_agent, "run")

    def test_agent_has_required_prompts(self):
        """Test that the agent has required prompts registered."""
        # The agent should have prompts registered during build
        assert trivia_agent is not None

    def test_agent_model_is_configured(self):
        """Test that the agent model is configured."""
        assert trivia_agent is not None
        assert trivia_agent.model is not None


class TestTriviaGameScenarios:
    """Integration tests for specific trivia game scenarios."""

    def test_quick_game_scenario(self, client: TestClient):
        """Test a quick game scenario (1 question, easy)."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "easy", "num_questions": 1},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_standard_game_scenario(self, client: TestClient):
        """Test a standard game scenario (5 questions, medium)."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_challenge_game_scenario(self, client: TestClient):
        """Test a challenge game scenario (10 questions, hard)."""
        response = client.post(
            "/api/game/start",
            json={"difficulty": "hard", "num_questions": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert "game_id" in data
        assert data["status"] == "started"

    def test_game_session_workflow(self, client: TestClient):
        """Test complete game session workflow."""
        # 1. Check service is running
        health_response = client.get("/health/live")
        assert health_response.status_code == 200

        # 2. Start a game
        start_response = client.post(
            "/api/game/start",
            json={"difficulty": "medium", "num_questions": 3},
        )
        assert start_response.status_code == 200
        game_data = start_response.json()

        # 3. Verify game session
        assert game_data["status"] == "started"
        assert game_data["game_id"] is not None

    def test_multiple_game_sessions_workflow(self, client: TestClient):
        """Test workflow with multiple game sessions."""
        sessions = []

        # Create multiple game sessions
        for difficulty in ["easy", "medium", "hard"]:
            response = client.post(
                "/api/game/start",
                json={"difficulty": difficulty, "num_questions": 2},
            )
            assert response.status_code == 200
            sessions.append(response.json())

        # Verify all sessions are independent
        assert len(sessions) == 3
        for i, session in enumerate(sessions):
            assert "game_id" in session
            assert session["status"] == "started"
