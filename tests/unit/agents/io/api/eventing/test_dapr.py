"""Unit tests for DaprEventing.publish."""

from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.models.result import ProcessingResult


def _wire_processing_result(mock_registry: MagicMock, result: ProcessingResult) -> None:
    """Configure mock registry's processing service to return `result`."""
    mock_registry.get_service.return_value.process_event = AsyncMock(return_value=result)
    mock_registry.correlation_context.set.return_value = MagicMock()


class TestDaprEventingPublish:
    async def test_processed_result_returns_success(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        processed_result: ProcessingResult,
    ) -> None:
        _wire_processing_result(mock_registry, processed_result)
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result == {"status": "SUCCESS"}

    async def test_no_handler_result_returns_retry(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        _wire_processing_result(mock_registry, unhandled_result)
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "RETRY"

    async def test_no_handler_retry_includes_reason(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        _wire_processing_result(mock_registry, unhandled_result)
        result = await dapr_eventing.publish("topic", cloud_event)
        assert "reason" in result

    async def test_retryable_error_returns_retry(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(
            side_effect=RetryableHandlerError(status="error", reason="transient failure")
        )
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "RETRY"
        assert result["reason"] == "transient failure"

    async def test_invalid_event_error_returns_drop(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(
            side_effect=InvalidEventError(status="invalid", reason="bad schema")
        )
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "DROP"
        assert result["reason"] == "bad schema"

    async def test_critical_error_returns_retry(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(side_effect=CriticalHandlerError(status="critical", reason="oom"))
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "RETRY"
        assert result["reason"] == "oom"


class TestDaprEventingSubscribe:
    async def test_subscription_document_is_empty_without_declarations(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        mock_registry.get_event_handler.return_value = []
        assert await dapr_eventing.subscribe() == []

    async def test_subscription_document_lists_declared_topics(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["orders.created", "orders.cancelled"]
        mock_registry.get_event_handler.return_value = [handler]

        assert await dapr_eventing.subscribe() == [
            {"pubsubname": "pubsub", "topic": "orders.created", "route": "/events/orders.created"},
            {"pubsubname": "pubsub", "topic": "orders.cancelled", "route": "/events/orders.cancelled"},
        ]

    async def test_subscription_document_deduplicates_across_handlers(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        first = MagicMock()
        first.get_subscribed_topics.return_value = ["orders.created"]
        second = MagicMock()
        second.get_subscribed_topics.return_value = ["orders.created"]
        mock_registry.get_event_handler.return_value = [first, second]

        document = await dapr_eventing.subscribe()

        assert [entry["topic"] for entry in document] == ["orders.created"]

    async def test_subscription_document_uses_configured_pubsub_name(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["orders.created"]
        mock_registry.get_event_handler.return_value = [handler]
        dapr_eventing.config.get.side_effect = lambda key, default=None: "orders-bus" if key == "dapr_pubsub_name" else default

        document = await dapr_eventing.subscribe()

        assert document[0]["pubsubname"] == "orders-bus"

    async def test_subscription_document_is_empty_when_declared_externally(
        self, dapr_eventing: DaprEventing, mock_registry: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["orders.created"]
        mock_registry.get_event_handler.return_value = [handler]
        dapr_eventing.config.get.side_effect = lambda key, default=None: True if key == "dapr_declarative_subscriptions" else default

        assert await dapr_eventing.subscribe() == []

    async def test_sidecar_can_fetch_the_document_without_query_parameters(
        self, dapr_eventing: DaprEventing, mock_registry: MagicMock
    ) -> None:
        """Regression: a required query parameter here answered 422 to every sidecar call."""
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["orders.created"]
        mock_registry.get_event_handler.return_value = [handler]

        app = FastAPI()
        app.include_router(dapr_eventing.router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sidecar") as client:
            response = await client.get("/dapr/subscribe")

        assert response.status_code == 200
        assert response.json() == [{"pubsubname": "pubsub", "topic": "orders.created", "route": "/events/orders.created"}]


class TestDaprEventingOnStartup:
    async def test_fetches_dapr_client_from_registry(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = []

        await dapr_eventing.on_startup()

        assert dapr_eventing._client is mock_client

    async def test_no_handlers_skips_client_subscribe(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = []

        await dapr_eventing.on_startup()

        mock_client.subscribe.assert_not_called()

    async def test_handler_topics_passed_to_client_subscribe(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["orders.created"]
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = [handler]

        await dapr_eventing.on_startup()

        mock_client.subscribe.assert_awaited_once()
        mapping = mock_client.subscribe.call_args[0][0]
        assert "orders.created" in mapping
        assert callable(mapping["orders.created"])

    async def test_on_startup_returns_without_raising(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        """on_startup must return immediately; subscribe() starts a background task."""
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["t"]
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = [handler]

        await dapr_eventing.on_startup()  # must not raise or hang
