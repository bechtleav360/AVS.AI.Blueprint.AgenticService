"""REST API for the customer support Q&A collaboration."""

import logging

from fastapi import HTTPException

from src.blueprint.agents.base import RestApi

from ..models import SupportRequest, SupportResponse
from ..services import SupportQAService

logger = logging.getLogger(__name__)


class SupportQARestApi(RestApi):
    """REST API for customer support Q&A operations."""

    def __init__(self) -> None:
        """Initialize the support Q&A REST API.

        The component registry and agents will be wired in by AppBuilder.
        """
        super().__init__(name="SupportQARestApi")

    async def on_startup(self) -> None:
        """Initialize the REST API by getting the support service from the registry."""
        self._support_service: SupportQAService = self.get_registry().get_service("support_qa_service")

    @RestApi.post("/support/ask", response_model=SupportResponse)
    async def ask_question(self, request: SupportRequest) -> SupportResponse:
        """Ask a customer support question and get an answer with validation.

        Args:
            request: Support request with question

        Returns:
            Complete support response with answer and validation
        """
        try:
            logger.info(f"Processing support question: {request.question}")
            result = await self._support_service.answer_question(
                question=request.question,
                category=request.category,
                context=request.context,
            )
            return result
        except Exception as e:
            logger.error(f"Error processing question: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @RestApi.get("/support/{session_id}", response_model=dict)
    async def get_session(self, session_id: str) -> dict:
        """Get a support session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Support session data
        """
        try:
            session = self._support_service.get_session(session_id)
            return session.model_dump()
        except ValueError as e:
            logger.error(f"Session not found: {e}")
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @RestApi.get("/support/sessions/list", response_model=list)
    async def list_sessions(self) -> list:
        """List all support sessions.

        Returns:
            List of session summaries
        """
        try:
            return self._support_service.list_sessions()
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            raise HTTPException(status_code=500, detail=str(e))
