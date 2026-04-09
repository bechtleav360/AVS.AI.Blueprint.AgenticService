"""REST API routes for the document summarizer."""

import logging

from fastapi import HTTPException

from blueprint.agents.io.api.rest_api_base import RestApiBase

from src.models.schemas import DocumentRequest, SummarizeResponse
from src.services.summarizer_service import SummarizerService

logger = logging.getLogger(__name__)


class SummarizerApi(RestApiBase):
    """Exposes document summarization endpoints."""

    def __init__(self) -> None:
        super().__init__()
        self._service: SummarizerService | None = None

    async def on_startup(self) -> None:
        """Resolve the summarizer service from the registry."""
        self._service = self.registry.get_service(SummarizerService)  # type: ignore[assignment]
        logger.info("SummarizerApi started")

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @RestApiBase.post(
        "/summarize",
        response_model=SummarizeResponse,
        summary="Summarize a document",
        tags=["Summarizer"],
    )
    async def summarize_document(self, request: DocumentRequest) -> SummarizeResponse:
        """Accept a document and return a structured summary."""
        assert self._service is not None, "Service not initialised"
        return await self._service.summarize(request)

    @RestApiBase.get(
        "/summaries/{document_id}",
        response_model=SummarizeResponse,
        summary="Retrieve a cached summary",
        tags=["Summarizer"],
    )
    async def get_summary(self, document_id: str) -> SummarizeResponse:
        """Return a previously generated summary by its document ID."""
        assert self._service is not None, "Service not initialised"
        result = await self._service.get_summary(document_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Summary not found for document_id={document_id}")
        return result
