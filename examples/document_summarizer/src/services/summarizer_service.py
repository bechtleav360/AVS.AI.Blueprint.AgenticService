"""Business service that orchestrates document summarization."""

import hashlib
import logging
from typing import Any

from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.agent.agent_runtime import AgentRuntime
from blueprint.agents.services.infrastructure.cache_service import CacheService

from src.models.schemas import DocumentRequest, DocumentSummary, SummarizeResponse

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "summaries"


class SummarizerService(ServiceBase):
    """Service that delegates document analysis to the LLM agent and manages caching."""

    def __init__(self) -> None:
        super().__init__()
        self._agent: AgentRuntime | None = None
        self._cache: CacheService | None = None

    async def on_startup(self) -> None:
        """Resolve the agent and optional cache service from the registry."""
        self._agent = self.registry.get_component("document_summarizer")
        if self.registry.has_cache():
            self._cache = self.registry.cache_service
        logger.info("SummarizerService started (cache=%s)", self._cache is not None)

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def summarize(self, request: DocumentRequest) -> SummarizeResponse:
        """Summarize a document, returning a cached result when available.

        Args:
            request: The document to summarize.

        Returns:
            A SummarizeResponse containing the document_id and structured summary.
        """
        document_id = self._hash_content(request.content)

        # Check cache
        if self._cache is not None:
            cached: dict[str, Any] | None = self._cache.get(document_id, namespace=CACHE_NAMESPACE)
            if cached is not None:
                logger.info("Cache hit for document_id=%s", document_id)
                return SummarizeResponse(
                    document_id=document_id,
                    summary=DocumentSummary(**cached),
                )

        # Build user prompt
        user_prompt = request.content
        if request.title:
            user_prompt = f"Title: {request.title}\n\n{request.content}"

        # Run the agent
        assert self._agent is not None, "Agent not initialised — was on_startup called?"
        result = await self._agent.run(user_prompt)
        summary: DocumentSummary = result.data  # type: ignore[assignment]

        # Cache the result
        if self._cache is not None:
            self._cache.set(
                document_id,
                summary.model_dump(),
                namespace=CACHE_NAMESPACE,
            )
            logger.info("Cached summary for document_id=%s", document_id)

        return SummarizeResponse(document_id=document_id, summary=summary)

    async def get_summary(self, document_id: str) -> SummarizeResponse | None:
        """Retrieve a previously cached summary by document ID.

        Args:
            document_id: The hash-based identifier of the document.

        Returns:
            The cached SummarizeResponse, or None if not found.
        """
        if self._cache is None:
            return None

        cached: dict[str, Any] | None = self._cache.get(document_id, namespace=CACHE_NAMESPACE)
        if cached is None:
            return None

        return SummarizeResponse(
            document_id=document_id,
            summary=DocumentSummary(**cached),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_content(content: str) -> str:
        """Derive a deterministic document ID from the content."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]
