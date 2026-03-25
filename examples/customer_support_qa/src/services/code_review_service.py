"""Customer support Q&A service with two-agent collaboration."""

import json
import logging
import uuid
from typing import Any

from src.blueprint.agents.agent import AgentBuilder
from src.blueprint.agents.services import ServiceBase
from pydantic_ai import AgentRunResult

from ..models import (
    SupportAnswer,
    SupportResponse,
    SupportSession,
    ValidationResult,
    ValidationStatus,
)

logger: logging.Logger = logging.getLogger(__name__)


class SupportQAService(ServiceBase):
    """Service for managing customer support Q&A with junior and senior agents."""

    sessions: dict[str, SupportSession]

    def __init__(self) -> None:
        """Initialize the support Q&A service."""
        super().__init__()
        self.sessions: dict[str, SupportSession] = {}

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def answer_question(
        self, question: str, category: str = "general", context: str = ""
    ) -> SupportResponse:
        """Answer a customer question with junior-senior collaboration.

        Args:
            question: Customer's question
            category: Question category
            context: Additional context

        Returns:
            Complete support response with answer and validation
        """
        session_id = str(uuid.uuid4())
        logger.info(f"Starting support session {session_id} for question: {question}")

        session = SupportSession(
            session_id=session_id,
            question=question,
            category=category,
        )
        self.sessions[session_id] = session

        junior_answer = await self._get_junior_answer(session_id, question, category, context)
        session.junior_answer = junior_answer

        senior_validation = await self._validate_answer(session_id, question, junior_answer)
        session.senior_validation = senior_validation

        return SupportResponse(
            session_id=session_id,
            question=question,
            answer=junior_answer.answer,
            confidence=junior_answer.confidence,
            sources=junior_answer.sources,
            validated=senior_validation.status == ValidationStatus.APPROVED,
            validation_reason=senior_validation.reason,
            status=senior_validation.status,
        )

    async def _get_junior_answer(
        self, session_id: str, question: str, category: str, context: str
    ) -> SupportAnswer:
        """Get detailed answer from junior support agent.

        Args:
            session_id: Session ID
            question: Customer's question
            category: Question category
            context: Additional context

        Returns:
            Support answer from junior agent
        """
        logger.info(f"Junior agent generating answer for session {session_id}")

        prompt = (
            self.registry
            .get_agent("junior_support")
            .get_prompt("answer_question")
            .format(question=question, category=category, context=context)
        )

        try:
            result: AgentRunResult = await self.registry.get_agent("junior_support").run(prompt)

            response_text = AgentBuilder.extract_response_text(result)
            usage = AgentBuilder.extract_usage_info(result)

            if usage:
                logger.info(
                    f"Junior answer generation - Tokens: input={usage.get('input_tokens')}, output={usage.get('output_tokens')}"
                )

            try:
                llm_response = json.loads(response_text)
                answer = llm_response.get("answer", response_text)
                confidence = float(llm_response.get("confidence", 0.7))
                sources = llm_response.get("sources", [])
            except (json.JSONDecodeError, KeyError, ValueError) as parse_error:
                logger.warning(f"Failed to parse junior agent response as JSON: {parse_error}")
                answer = response_text
                confidence = 0.7
                sources = []

            return SupportAnswer(
                session_id=session_id,
                answer=answer,
                confidence=max(0.0, min(1.0, confidence)),
                sources=sources if isinstance(sources, list) else [],
            )

        except Exception as e:
            logger.error(f"Error generating answer with junior agent: {e}")
            return SupportAnswer(
                session_id=session_id,
                answer=f"I apologize, but I encountered an error: {str(e)}",
                confidence=0.0,
                sources=[],
            )

    async def _validate_answer(
        self, session_id: str, question: str, junior_answer: SupportAnswer
    ) -> ValidationResult:
        """Validate answer from senior support agent.

        Args:
            session_id: Session ID
            question: Original question
            junior_answer: Junior's answer

        Returns:
            Validation result from senior agent
        """
        logger.info(f"Senior agent validating answer for session {session_id}")

        prompt = (
            self.registry
            .get_agent("senior_support")
            .get_prompt("validate_answer")
            .format(
                question=question,
                answer=junior_answer.answer,
                confidence=junior_answer.confidence,
            )
        )

        try:
            result: AgentRunResult = await self.registry.get_agent("senior_support").run(prompt)

            response_text = AgentBuilder.extract_response_text(result)
            usage = AgentBuilder.extract_usage_info(result)

            if usage:
                logger.info(
                    f"Senior validation - Tokens: input={usage.get('input_tokens')}, output={usage.get('output_tokens')}"
                )

            try:
                llm_response = json.loads(response_text)
                status_str = llm_response.get("status", "approved").lower()
                reason = llm_response.get("reason", response_text)

                if "reject" in status_str:
                    status = ValidationStatus.REJECTED
                elif "revision" in status_str:
                    status = ValidationStatus.NEEDS_REVISION
                else:
                    status = ValidationStatus.APPROVED
            except (json.JSONDecodeError, KeyError) as parse_error:
                logger.warning(f"Failed to parse senior agent response as JSON: {parse_error}")
                status = ValidationStatus.APPROVED if "approved" in response_text.lower() else ValidationStatus.REJECTED
                reason = response_text

            return ValidationResult(
                session_id=session_id,
                status=status,
                reason=reason,
            )

        except Exception as e:
            logger.error(f"Error validating answer with senior agent: {e}")
            return ValidationResult(
                session_id=session_id,
                status=ValidationStatus.REJECTED,
                reason=f"Error during validation: {str(e)}",
            )

    def get_session(self, session_id: str) -> SupportSession:
        """Get a support session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Support session data

        Raises:
            ValueError: If session not found
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        return self.sessions[session_id]

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all support sessions.

        Returns:
            List of session summaries
        """
        return [
            {
                "session_id": session.session_id,
                "question": session.question,
                "category": session.category,
                "validated": session.senior_validation.status == ValidationStatus.APPROVED if session.senior_validation else None,
            }
            for session in self.sessions.values()
        ]
