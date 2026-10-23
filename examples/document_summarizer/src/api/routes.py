"""REST API routes for the document summarizer."""

import logging

from fastapi import HTTPException

from blueprint.agents.io.api.rest_api_base import RestApiBase

from src.models.domain_models import Document
from src.models.dto import DocumentRequest, SummarizeResponse
from src.services.summarizer_service import SummarizerService

logger = logging.getLogger(__name__)


class SummarizerApi(RestApiBase):
    """Exposes document summarization endpoints."""

    async def on_startup(self) -> None:
        """Resolve the summarizer service from the registry."""
        self._service: SummarizerService = self.registry.get_service(SummarizerService)  # type: ignore[assignment]
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
        record = await self._service.summarize(Document(content=request.content, title=request.title))
        return SummarizeResponse(document_id=record.document_id, summary=record.summary)

    @RestApiBase.get(
        "/summaries/{document_id}",
        response_model=SummarizeResponse,
        summary="Retrieve a cached summary",
        tags=["Summarizer"],
    )
    async def get_summary(self, document_id: str) -> SummarizeResponse:
        """Return a previously generated summary by its document ID."""
        record = await self._service.get_summary(document_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Summary not found for document_id={document_id}")
        return SummarizeResponse(document_id=record.document_id, summary=record.summary)
