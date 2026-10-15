"""Unit tests for WebhookHandler: it translates, the service decides."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from src.handlers.webhook_handler import WebhookHandler
from src.models.domain import IncomingWebhook, RelayOutcome
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
async def handler_and_service():
    """A WebhookHandler holding a WebhookService double, as ``on_startup`` would leave it."""
    service = MagicMock(spec=WebhookService)
    service.relay = AsyncMock(return_value=RelayOutcome(kind="processed", data={"webhook_id": "evt-test-001"}))
    handler = WebhookHandler.__new__(WebhookHandler)
    handler._priority = 10
    handler._service = service
    return handler, service


class TestRouting:
    async def test_declares_and_accepts_webhook_received(self, handler_and_service):
        handler, _ = handler_and_service
        assert handler.get_handled_event_types() == ["webhook.received"]
        assert await handler.can_handle_event(_make_event(_github_push_data()), {}) is True

    async def test_declines_other_types_without_calling_the_service(self, handler_and_service):
        handler, service = handler_and_service
        assert await handler.can_handle_event(_make_event({}, event_type="other.event"), {}) is False
        service.relay.assert_not_awaited()


class TestTranslation:
    async def test_the_payload_reaches_the_service_as_a_domain_value(self, handler_and_service):
        handler, service = handler_and_service
        await handler.handle_event(_make_event(_github_push_data()), {})
        webhook = service.relay.await_args.args[0]
        assert isinstance(webhook, IncomingWebhook)
        assert webhook.webhook_id == "evt-test-001"  # no webhook_id in the payload -> the event id
        assert webhook.source == "github"

    async def test_processed_is_published_as_webhook_processed(self, handler_and_service):
        handler, _ = handler_and_service
        result = await handler.handle_event(_make_event(_stripe_payment_data()), {})
        assert isinstance(result, HandlerResult)
        assert result.event_type == "webhook.processed"

    async def test_filtered_is_published_as_webhook_filtered(self, handler_and_service):
        handler, service = handler_and_service
        service.relay.return_value = RelayOutcome(kind="filtered", reason="bot", data={"reason": "bot"})
        result = await handler.handle_event(_make_event(_github_bot_data()), {})
        assert result.event_type == "webhook.filtered"
        assert result.data == {"reason": "bot"}

    async def test_a_duplicate_is_skipped_with_the_services_reason(self, handler_and_service):
        handler, service = handler_and_service
        service.relay.return_value = RelayOutcome(kind="duplicate", reason="webhook evt-test-001 already relayed")
        result = await handler.handle_event(_make_event(_stripe_test_data()), {})
        assert result.is_skipped
        assert result.skip_reason == "webhook evt-test-001 already relayed"
