"""Unit tests for WebhookService normalisation and deduplication logic."""

from __future__ import annotations

from unittest.mock import MagicMock


from src.models.schemas import NormalizedEvent, WebhookPayload
from src.services.webhook_service import WebhookService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(*, with_cache: bool = False) -> WebhookService:
    """Instantiate a WebhookService without touching the real registry."""
    svc = WebhookService.__new__(WebhookService)
    svc._name = "webhook_service"

    if with_cache:
        cache = MagicMock()
        cache.exists.return_value = False
        svc._cache = cache
    else:
        svc._cache = None

    return svc


# ---------------------------------------------------------------------------
# Normalisation tests
# ---------------------------------------------------------------------------


class TestNormalizePayload:
    def test_github_push(self):
        payload = WebhookPayload(
            source="github",
            event_type="push",
            payload={
                "action": "completed",
                "sender": {"login": "octocat"},
                "repository": {"full_name": "octocat/Hello-World"},
            },
        )
        svc = _make_service()
        result = svc.normalize_payload(payload)

        assert isinstance(result, NormalizedEvent)
        assert result.original_source == "github"
        assert result.event_category == "push"
        assert result.event_action == "completed"
        assert result.actor == "octocat"
        assert result.resource_id == "octocat/Hello-World"
        assert result.resource_type == "repository"

    def test_stripe_payment_intent(self):
        payload = WebhookPayload(
            source="stripe",
            event_type="payment_intent.succeeded",
            payload={
                "type": "payment_intent.succeeded",
                "object": "payment_intent",
                "id": "pi_abc",
            },
        )
        svc = _make_service()
        result = svc.normalize_payload(payload)

        assert result.original_source == "stripe"
        assert result.event_category == "payment_intent"
        assert result.event_action == "succeeded"
        assert result.resource_id == "pi_abc"
        assert result.resource_type == "payment_intent"

    def test_generic_passthrough(self):
        payload = WebhookPayload(
            source="generic",
            event_type="alert.fired",
            payload={
                "actor": "monitoring",
                "resource_id": "svc-42",
                "resource_type": "service",
                "severity": "critical",
            },
        )
        svc = _make_service()
        result = svc.normalize_payload(payload)

        assert result.original_source == "generic"
        assert result.event_category == "alert.fired"
        assert result.actor == "monitoring"
        assert result.resource_id == "svc-42"
        assert result.resource_type == "service"
        # Metadata should contain the full original payload
        assert result.metadata["severity"] == "critical"

    def test_github_missing_optional_fields(self):
        payload = WebhookPayload(
            source="github",
            event_type="ping",
            payload={},
        )
        svc = _make_service()
        result = svc.normalize_payload(payload)

        assert result.original_source == "github"
        assert result.event_action == "ping"
        assert result.actor is None
        assert result.resource_id is None


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_not_duplicate_without_cache(self):
        svc = _make_service(with_cache=False)
        assert svc.is_duplicate("wh-1") is False

    def test_not_duplicate_with_cache(self):
        svc = _make_service(with_cache=True)
        svc._cache.exists.return_value = False  # type: ignore
        assert svc.is_duplicate("wh-1") is False

    def test_duplicate_detected(self):
        svc = _make_service(with_cache=True)
        svc._cache.exists.return_value = True  # type: ignore
        assert svc.is_duplicate("wh-1") is True

    def test_mark_processed_calls_cache_set(self):
        svc = _make_service(with_cache=True)
        svc.mark_processed("wh-2")
        svc._cache.set.assert_called_once()  # type: ignore
        call_args = svc._cache.set.call_args  # type: ignore
        assert call_args[0][0] == "wh-2"

    def test_mark_processed_noop_without_cache(self):
        svc = _make_service(with_cache=False)
        # Should not raise
        svc.mark_processed("wh-3")


# ---------------------------------------------------------------------------
# Recent tracking tests
# ---------------------------------------------------------------------------


class TestRecentTracking:
    def test_store_recent_with_cache(self):
        svc = _make_service(with_cache=True)
        data = {"webhook_id": "wh-10", "event_category": "push"}
        svc.store_recent("wh-10", data)
        svc._cache.set.assert_called_once()  # type: ignore

    def test_store_recent_noop_without_cache(self):
        svc = _make_service(with_cache=False)
        svc.store_recent("wh-10", {})  # should not raise

    def test_get_recent_empty_without_cache(self):
        svc = _make_service(with_cache=False)
        assert svc.get_recent() == []
