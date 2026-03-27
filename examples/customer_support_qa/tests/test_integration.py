"""Integration tests for customer support Q&A system."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from src.main import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client."""
    return TestClient(app)


class TestSupportQAIntegration:
    """Integration tests for the complete Q&A workflow."""

    @pytest.mark.asyncio
    async def test_complete_qa_workflow(self, client: TestClient) -> None:
        """Test complete workflow from question to validated answer."""
        with (
            patch("src.services.code_review_service.SupportQAService._get_junior_answer") as mock_junior,
            patch("src.services.code_review_service.SupportQAService._validate_answer") as mock_senior,
        ):

            from src.models import SupportAnswer, ValidationResult, ValidationStatus

            mock_junior.return_value = SupportAnswer(
                session_id="integration-test",
                answer="To reset your password:\n1. Click 'Forgot Password'\n2. Enter your email\n3. Check your inbox for reset link\n4. Follow the link and create new password",
                confidence=0.85,
                sources=["KB-1234: Password Reset", "KB-5678: Account Security"],
            )

            mock_senior.return_value = ValidationResult(
                session_id="integration-test",
                status=ValidationStatus.APPROVED,
                reason="Clear step-by-step instructions provided.",
            )

            response = client.post(
                "/api/support/ask",
                json={
                    "question": "How do I reset my password?",
                    "category": "technical",
                    "context": "User cannot remember password",
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert "session_id" in data
            assert data["question"] == "How do I reset my password?"
            assert "password" in data["answer"].lower()
            assert data["confidence"] == 0.85
            assert len(data["sources"]) == 2
            assert data["validated"] is True
            assert data["status"] == "approved"

            session_id = data["session_id"]

            session_response = client.get(f"/api/support/{session_id}")
            assert session_response.status_code == 200
            session_data = session_response.json()
            assert session_data["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_rejected_answer_workflow(self, client: TestClient) -> None:
        """Test workflow where senior rejects junior's answer."""
        with (
            patch("src.services.code_review_service.SupportQAService._get_junior_answer") as mock_junior,
            patch("src.services.code_review_service.SupportQAService._validate_answer") as mock_senior,
        ):

            from src.models import SupportAnswer, ValidationResult, ValidationStatus

            mock_junior.return_value = SupportAnswer(
                session_id="rejection-test",
                answer="I'm not sure about that.",
                confidence=0.3,
                sources=[],
            )

            mock_senior.return_value = ValidationResult(
                session_id="rejection-test",
                status=ValidationStatus.REJECTED,
                reason="Answer is too vague and lacks specific information.",
            )

            response = client.post(
                "/api/support/ask",
                json={
                    "question": "What are the system requirements?",
                    "category": "technical",
                    "context": "",
                },
            )

            assert response.status_code == 200
            data = response.json()

            assert data["validated"] is False
            assert data["status"] == "rejected"
            assert "vague" in data["validation_reason"].lower()

    @pytest.mark.asyncio
    async def test_multiple_questions_session_tracking(self, client: TestClient) -> None:
        """Test that multiple questions create separate sessions."""
        with (
            patch("src.services.code_review_service.SupportQAService._get_junior_answer") as mock_junior,
            patch("src.services.code_review_service.SupportQAService._validate_answer") as mock_senior,
        ):

            from src.models import SupportAnswer, ValidationResult, ValidationStatus

            mock_junior.return_value = SupportAnswer(
                session_id="test",
                answer="Test answer",
                confidence=0.8,
                sources=[],
            )

            mock_senior.return_value = ValidationResult(
                session_id="test",
                status=ValidationStatus.APPROVED,
                reason="Good answer.",
            )

            response1 = client.post(
                "/api/support/ask",
                json={"question": "Question 1", "category": "general", "context": ""},
            )

            response2 = client.post(
                "/api/support/ask",
                json={"question": "Question 2", "category": "technical", "context": ""},
            )

            assert response1.status_code == 200
            assert response2.status_code == 200

            session_id1 = response1.json()["session_id"]
            session_id2 = response2.json()["session_id"]

            assert session_id1 != session_id2

            sessions_response = client.get("/api/support/sessions/list")
            assert sessions_response.status_code == 200
            sessions = sessions_response.json()
            assert len(sessions) >= 2

    def test_health_check(self, client: TestClient) -> None:
        """Test that health check endpoint works."""
        response = client.get("/health/live")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_different_categories(self, client: TestClient) -> None:
        """Test questions from different categories."""
        with (
            patch("src.services.code_review_service.SupportQAService._get_junior_answer") as mock_junior,
            patch("src.services.code_review_service.SupportQAService._validate_answer") as mock_senior,
        ):

            from src.models import SupportAnswer, ValidationResult, ValidationStatus

            def create_answer(session_id: str, category: str) -> SupportAnswer:
                return SupportAnswer(
                    session_id=session_id,
                    answer=f"Answer for {category} question",
                    confidence=0.8,
                    sources=[f"KB-{category}"],
                )

            mock_junior.side_effect = lambda sid, q, cat, ctx: create_answer(sid, cat)
            mock_senior.return_value = ValidationResult(
                session_id="test",
                status=ValidationStatus.APPROVED,
                reason="Good.",
            )

            categories = ["technical", "billing", "product", "general"]

            for category in categories:
                response = client.post(
                    "/api/support/ask",
                    json={
                        "question": f"Test question for {category}",
                        "category": category,
                        "context": "",
                    },
                )

                assert response.status_code == 200
                data = response.json()
                assert category in data["answer"].lower()
