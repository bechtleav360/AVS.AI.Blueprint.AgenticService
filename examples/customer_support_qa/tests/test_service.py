"""Tests for customer support Q&A service."""

import pytest
from unittest.mock import patch

from src.services.code_review_service import SupportQAService
from src.models import SupportAnswer, ValidationResult, ValidationStatus


class TestSupportQAService:
    """Test cases for SupportQAService."""

    @pytest.fixture
    def service(self) -> SupportQAService:
        """Create a service instance."""
        return SupportQAService()

    @pytest.mark.asyncio
    async def test_answer_question(self, service: SupportQAService) -> None:
        """Test answering a question."""
        with patch.object(service, "_get_junior_answer") as mock_junior, \
             patch.object(service, "_validate_answer") as mock_senior:

            mock_junior.return_value = SupportAnswer(
                session_id="test-123",
                answer="Here is how to reset your password...",
                confidence=0.9,
                sources=["KB-1234"],
            )

            mock_senior.return_value = ValidationResult(
                session_id="test-123",
                status=ValidationStatus.APPROVED,
                reason="Answer is accurate and helpful.",
            )

            result = await service.answer_question(
                question="How do I reset my password?",
                category="technical",
                context="User forgot password",
            )

            assert "password" in result.answer.lower()
            assert result.validated is True
            assert result.confidence == 0.9
            assert result.status == ValidationStatus.APPROVED

    def test_get_session(self, service: SupportQAService) -> None:
        """Test getting a session."""
        with pytest.raises(ValueError, match="not found"):
            service.get_session("nonexistent")

    def test_list_sessions(self, service: SupportQAService) -> None:
        """Test listing sessions."""
        sessions = service.list_sessions()
        assert isinstance(sessions, list)
        assert len(sessions) == 0
