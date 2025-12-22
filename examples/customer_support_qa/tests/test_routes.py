"""Tests for customer support Q&A REST API routes."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from src.main import app
from src.models import SupportResponse, ValidationStatus


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_support_response() -> SupportResponse:
    """Create a mock support response."""
    return SupportResponse(
        session_id="test-session-123",
        question="How do I reset my password?",
        answer="To reset your password, follow these steps: 1. Go to the login page...",
        confidence=0.9,
        sources=["KB-1234: Password Reset Guide"],
        validated=True,
        validation_reason="Answer is accurate and comprehensive.",
        status=ValidationStatus.APPROVED,
    )


class TestSupportQARoutes:
    """Test cases for customer support Q&A REST API routes."""

    @pytest.mark.asyncio
    async def test_ask_question_success(
        self, client: TestClient, mock_support_response: SupportResponse
    ) -> None:
        """Test successful question answering."""
        with patch("src.services.code_review_service.SupportQAService.answer_question") as mock_answer:
            mock_answer.return_value = mock_support_response

            response = client.post(
                "/api/support/ask",
                json={
                    "question": "How do I reset my password?",
                    "category": "technical",
                    "context": "User forgot password",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["session_id"] == "test-session-123"
            assert data["validated"] is True
            assert data["confidence"] == 0.9

    def test_ask_question_invalid_request(self, client: TestClient) -> None:
        """Test question with invalid request."""
        response = client.post(
            "/api/support/ask",
            json={},
        )

        assert response.status_code == 422

    def test_get_session_not_found(self, client: TestClient) -> None:
        """Test getting non-existent session."""
        response = client.get("/api/support/nonexistent-session")

        assert response.status_code == 404

    def test_list_sessions(self, client: TestClient) -> None:
        """Test listing all sessions."""
        response = client.get("/api/support/sessions/list")

        assert response.status_code == 200
        assert isinstance(response.json(), list)
