"""Unit tests for the webhook relay handler chain."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from src.handlers.content_filter import ContentFilter
from src.handlers.metadata_enricher import MetadataEnricher
from src.handlers.webhook_normalizer import WebhookNormalizer
from src.models.schemas import NormalizedEvent
from src.services.webhook_service import WebhookService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_event(data: dict[str, Any], event_type: str = "webhook.received") -> GenericCloudEvent:
    return GenericCloudEvent(
        id="evt-test-001",
        type=event_type,
        source="/tests",
        time=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        data=data,
    )  # type: ignore


def _github_push_data() -> dict[str, Any]:
    return {
        "source": "github",
        "event_type": "push",
        "payload": {
            "action": "completed",
            "sender": {"login": "octocat"},
            "repository": {"full_name": "octocat/Hello-World"},
        },
    }


def _github_bot_data() -> dict[str, Any]:
    return {
        "source": "github",
        "event_type": "push",
        "payload": {
            "action": "completed",
            "sender": {"login": "dependabot[bot]"},
            "repository": {"full_name": "org/repo"},
        },
    }


def _stripe_payment_data() -> dict[str, Any]:
    return {
        "source": "stripe",
        "event_type": "payment_intent.succeeded",
        "payload": {
            "type": "payment_intent.succeeded",
            "object": "payment_intent",
            "id": "pi_123",
        },
    }


def _stripe_test_data() -> dict[str, Any]:
    return {
        "source": "stripe",
        "event_type": "test_charge.created",
        "payload": {
            "type": "test_charge.created",
            "object": "charge",
            "id": "ch_test_1",
        },
    }


@pytest.fixture()
def mock_registry():
    """Return a mock registry with a fake WebhookService."""
    service = MagicMock(spec=WebhookService)
    service.is_duplicate.return_value = False
    service.normalize_payload.side_effect = lambda p: WebhookService._normalize_github(p)
    service.mark_processed = MagicMock()
    service.store_recent = MagicMock()

    registry = MagicMock()
    registry.get_service.return_value = service
    return registry


# ---------------------------------------------------------------------------
# WebhookNormalizer
# ---------------------------------------------------------------------------


class TestWebhookNormalizer:
    @pytest.mark.asyncio
    async def test_can_handle_correct_event_type(self):
        handler = WebhookNormalizer.__new__(WebhookNormalizer)
        handler._priority = 5
        event = _make_event(_github_push_data())
        assert await handler.can_handle_event(event, {}) is True

    @pytest.mark.asyncio
    async def test_ignores_other_event_types(self):
        handler = WebhookNormalizer.__new__(WebhookNormalizer)
        handler._priority = 5
        event = _make_event(_github_push_data(), event_type="order.placed")
        assert await handler.can_handle_event(event, {}) is False

    @pytest.mark.asyncio
    async def test_normalizes_and_passes(self, mock_registry):
        handler = WebhookNormalizer.__new__(WebhookNormalizer)
        handler._priority = 5
        handler._name = "webhook_normalizer"
        type(handler).registry = property(lambda self: mock_registry)  # type: ignore

        event = _make_event(_github_push_data())
        context: dict[str, Any] = {}
        result = await handler.handle_event(event, context)

        assert result is None
        assert "normalized_event" in context
        assert context["normalized_event"]["original_source"] == "github"

    @pytest.mark.asyncio
    async def test_duplicate_skipped(self, mock_registry):
        mock_registry.get_service.return_value.is_duplicate.return_value = True

        handler = WebhookNormalizer.__new__(WebhookNormalizer)
        handler._priority = 5
        handler._name = "webhook_normalizer"
        type(handler).registry = property(lambda self: mock_registry)  # type: ignore

        event = _make_event(_github_push_data())
        context: dict[str, Any] = {}
        result = await handler.handle_event(event, context)

        assert result is None
        assert "normalized_event" not in context


# ---------------------------------------------------------------------------
# ContentFilter
# ---------------------------------------------------------------------------


class TestContentFilter:
    @pytest.mark.asyncio
    async def test_allows_normal_event(self):
        handler = ContentFilter.__new__(ContentFilter)
        handler._priority = 10

        context = {
            "normalized_event": {
                "original_source": "github",
                "event_category": "push",
                "actor": "octocat",
            },
            "webhook_id": "wh-1",
        }
        event = _make_event(_github_push_data())
        result = await handler.handle_event(event, context)
        assert result is None

    @pytest.mark.asyncio
    async def test_filters_github_bot(self):
        handler = ContentFilter.__new__(ContentFilter)
        handler._priority = 10

        context = {
            "normalized_event": {
                "original_source": "github",
                "event_category": "push",
                "actor": "dependabot[bot]",
            },
            "webhook_id": "wh-2",
        }
        event = _make_event(_github_bot_data())
        result = await handler.handle_event(event, context)

        assert isinstance(result, HandlerResult)
        assert result.event_type == "webhook.filtered"
        assert "bot" in result.data["reason"].lower()  # type: ignore

    @pytest.mark.asyncio
    async def test_filters_stripe_test(self):
        handler = ContentFilter.__new__(ContentFilter)
        handler._priority = 10

        context = {
            "normalized_event": {
                "original_source": "stripe",
                "event_category": "test_charge",
                "actor": None,
            },
            "webhook_id": "wh-3",
        }
        event = _make_event(_stripe_test_data())
        result = await handler.handle_event(event, context)

        assert isinstance(result, HandlerResult)
        assert result.event_type == "webhook.filtered"
        assert "test" in result.data["reason"].lower()  # type: ignore


# ---------------------------------------------------------------------------
# MetadataEnricher
# ---------------------------------------------------------------------------


class TestMetadataEnricher:
    @pytest.mark.asyncio
    async def test_enriches_and_publishes(self, mock_registry):
        handler = MetadataEnricher.__new__(MetadataEnricher)
        handler._priority = 15
        handler._name = "metadata_enricher"
        type(handler).registry = property(lambda self: mock_registry)  # type: ignore

        context = {
            "normalized_event": {
                "original_source": "github",
                "event_category": "push",
                "event_action": "completed",
                "actor": "octocat",
            },
            "webhook_id": "wh-4",
        }
        event = _make_event(_github_push_data())
        result = await handler.handle_event(event, context)

        assert isinstance(result, HandlerResult)
        assert result.event_type == "webhook.processed"
        assert result.data["priority_score"] == 50  # "push" keyword # type: ignore
        assert "processed_at" in result.data  # type: ignore
        mock_registry.get_service.return_value.mark_processed.assert_called_once_with("wh-4")

    @pytest.mark.asyncio
    async def test_payment_gets_high_priority(self, mock_registry):
        handler = MetadataEnricher.__new__(MetadataEnricher)
        handler._priority = 15
        handler._name = "metadata_enricher"
        type(handler).registry = property(lambda self: mock_registry)  # type: ignore

        context = {
            "normalized_event": {
                "original_source": "stripe",
                "event_category": "payment_intent",
                "event_action": "succeeded",
            },
            "webhook_id": "wh-5",
        }
        event = _make_event(_stripe_payment_data())
        result = await handler.handle_event(event, context)

        assert isinstance(result, HandlerResult)
        assert result.data["priority_score"] == 80  # "payment" keyword # type: ignore
