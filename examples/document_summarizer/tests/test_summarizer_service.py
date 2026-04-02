"""Unit tests for SummarizerService with mocked agent and cache."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.schemas import DocumentRequest, DocumentSummary, SummarizeResponse
from src.services.summarizer_service import SummarizerService, CACHE_NAMESPACE


def _make_summary() -> DocumentSummary:
    return DocumentSummary(
        title="Test Document",
        summary="A short test summary.",
        key_points=["point one", "point two", "point three"],
        sentiment="neutral",
        word_count=50,
        reading_time_minutes=0.25,
    )


def _make_request(content: str = "Some document content for testing.", title: str | None = None) -> DocumentRequest:
    return DocumentRequest(content=content, title=title)


class TestSummarize:
    @pytest.mark.asyncio
    async def test_returns_summary_from_agent(self) -> None:
        """When cache is empty the service should call the agent and return its result."""
        service = SummarizerService.__new__(SummarizerService)
        summary = _make_summary()

        mock_result = MagicMock()
        mock_result.data = summary

        service._agent = AsyncMock()
        service._agent.run = AsyncMock(return_value=mock_result)
        service._cache = None

        request = _make_request()
        response = await service.summarize(request)

        assert isinstance(response, SummarizeResponse)
        assert response.summary == summary
        assert len(response.document_id) == 16
        service._agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_agent(self) -> None:
        """When the summary is already cached the agent should not be called."""
        service = SummarizerService.__new__(SummarizerService)
        summary = _make_summary()

        mock_cache = MagicMock()
        mock_cache.get.return_value = summary.model_dump()

        service._agent = AsyncMock()
        service._cache = mock_cache

        request = _make_request()
        response = await service.summarize(request)

        assert response.summary == summary
        service._agent.run.assert_not_awaited()
        mock_cache.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_stores_result(self) -> None:
        """On a cache miss the result should be stored in the cache."""
        service = SummarizerService.__new__(SummarizerService)
        summary = _make_summary()

        mock_result = MagicMock()
        mock_result.data = summary

        mock_cache = MagicMock()
        mock_cache.get.return_value = None

        service._agent = AsyncMock()
        service._agent.run = AsyncMock(return_value=mock_result)
        service._cache = mock_cache

        request = _make_request()
        response = await service.summarize(request)

        assert response.summary == summary
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args.kwargs.get("namespace") == CACHE_NAMESPACE or call_args[2] == CACHE_NAMESPACE

    @pytest.mark.asyncio
    async def test_title_prepended_to_prompt(self) -> None:
        """When a title is provided it should be prepended to the user prompt."""
        service = SummarizerService.__new__(SummarizerService)
        summary = _make_summary()

        mock_result = MagicMock()
        mock_result.data = summary

        service._agent = AsyncMock()
        service._agent.run = AsyncMock(return_value=mock_result)
        service._cache = None

        request = _make_request(title="My Title")
        await service.summarize(request)

        prompt_sent = service._agent.run.call_args[0][0]
        assert "My Title" in prompt_sent


class TestGetSummary:
    @pytest.mark.asyncio
    async def test_returns_none_without_cache(self) -> None:
        service = SummarizerService.__new__(SummarizerService)
        service._cache = None

        result = await service.get_summary("abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_cache_miss(self) -> None:
        service = SummarizerService.__new__(SummarizerService)
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        service._cache = mock_cache

        result = await service.get_summary("abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_cached_summary(self) -> None:
        service = SummarizerService.__new__(SummarizerService)
        summary = _make_summary()
        mock_cache = MagicMock()
        mock_cache.get.return_value = summary.model_dump()
        service._cache = mock_cache

        result = await service.get_summary("abc123")
        assert result is not None
        assert result.summary == summary
        assert result.document_id == "abc123"


class TestHashContent:
    def test_deterministic(self) -> None:
        id1 = SummarizerService._hash_content("hello")
        id2 = SummarizerService._hash_content("hello")
        assert id1 == id2

    def test_different_content_different_id(self) -> None:
        id1 = SummarizerService._hash_content("hello")
        id2 = SummarizerService._hash_content("world")
        assert id1 != id2

    def test_length(self) -> None:
        doc_id = SummarizerService._hash_content("some content")
        assert len(doc_id) == 16
