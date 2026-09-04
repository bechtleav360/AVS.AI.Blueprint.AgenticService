"""Unit tests for DaprEventing.publish."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from blueprint.agents.io.api.eventing.dapr import DaprDeliveryRoute, DaprEventing
from blueprint.agents.io.api.eventing.dapr_response import dapr_status
from blueprint.agents.io.api.eventing.nats import NatsEventing
from blueprint.agents.models.errors import (
    CriticalHandlerError,
    DeliveryDisposition,
    InvalidEventError,
    RetryableHandlerError,
    disposition_for,
)
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

    async def test_no_handler_result_returns_success(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        """Redelivery cannot make a handler appear, and under a queue group RETRY walks every replica."""
        _wire_processing_result(mock_registry, unhandled_result)
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result == {"status": "SUCCESS"}

    async def test_no_handler_result_is_not_reported_as_a_fault(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An agent finding no work in an event is normal, not a problem the blueprint reports."""
        _wire_processing_result(mock_registry, unhandled_result)
        with caplog.at_level("DEBUG"):
            await dapr_eventing.publish("topic", cloud_event)
        assert [r for r in caplog.records if r.levelname in {"WARNING", "ERROR", "CRITICAL"}] == []

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

    async def test_critical_error_returns_drop(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        """A critical error is not made less critical by being delivered again."""
        mock_registry.get_service.return_value.process_event = AsyncMock(side_effect=CriticalHandlerError(status="critical", reason="oom"))
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "DROP"
        assert result["reason"] == "oom"

    async def test_unexpected_exception_returns_retry(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        """Previously a 500, which left the disposition to the sidecar's own policy."""
        mock_registry.get_service.return_value.process_event = AsyncMock(side_effect=RuntimeError("boom"))
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "RETRY"
        assert result["reason"] == "boom"

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (RetryableHandlerError(status="e", reason="r"), "RETRY"),
            (InvalidEventError(status="e", reason="r"), "DROP"),
            (CriticalHandlerError(status="e", reason="r"), "DROP"),
            (RuntimeError("boom"), "RETRY"),
        ],
        ids=["retryable", "invalid", "critical", "unexpected"],
    )
    async def test_matches_the_nats_disposition_for_the_same_error(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        error: Exception,
        expected: str,
    ) -> None:
        """Both transports render one shared decision; this pins the rendering."""
        assert dapr_status(disposition_for(error)) == expected

        mock_registry.get_service.return_value.process_event = AsyncMock(side_effect=error)
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == expected


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


class TestDaprEventingUnparseableDelivery:
    """P2 -- a body that cannot become a CloudEvent drops, as it terms under NATS."""

    @staticmethod
    def _app(dapr_eventing: DaprEventing) -> FastAPI:
        app = FastAPI()
        app.include_router(dapr_eventing.router)
        return app

    async def test_malformed_body_answers_drop_not_422(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        async with AsyncClient(transport=ASGITransport(app=self._app(dapr_eventing)), base_url="http://sidecar") as client:
            response = await client.post("/events/orders.created", json={"not": "a cloud event"})

        assert response.status_code == 200
        assert response.json()["status"] == "DROP"

    async def test_malformed_body_is_not_dispatched(self, dapr_eventing: DaprEventing, mock_registry: MagicMock) -> None:
        process_event = AsyncMock()
        mock_registry.get_service.return_value.process_event = process_event

        async with AsyncClient(transport=ASGITransport(app=self._app(dapr_eventing)), base_url="http://sidecar") as client:
            await client.post("/events/orders.created", json={"not": "a cloud event"})

        process_event.assert_not_awaited()

    async def test_drop_matches_what_nats_does_with_the_same_payload(self, dapr_eventing: DaprEventing) -> None:
        """NATS terms an undecodable payload; DROP is the same disposition in Dapr's words."""
        assert dapr_status(DeliveryDisposition.TERM) == "DROP"

    async def test_unparseable_delivery_is_logged(
        self, dapr_eventing: DaprEventing, mock_registry: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        async with AsyncClient(transport=ASGITransport(app=self._app(dapr_eventing)), base_url="http://sidecar") as client:
            with caplog.at_level("ERROR"):
                await client.post("/events/orders.created", json={"not": "a cloud event"})

        assert "unparseable delivery" in caplog.text

    async def test_a_valid_delivery_is_unaffected(
        self, dapr_eventing: DaprEventing, mock_registry: MagicMock, cloud_event: CloudEvent, processed_result: ProcessingResult
    ) -> None:
        _wire_processing_result(mock_registry, processed_result)

        async with AsyncClient(transport=ASGITransport(app=self._app(dapr_eventing)), base_url="http://sidecar") as client:
            response = await client.post("/events/orders.created", json=dict(cloud_event))

        assert response.status_code == 200
        assert response.json() == {"status": "SUCCESS"}


class TestDaprEventingManualInjection:
    """POST /events/{topic} is also the hand-injection path used when no broker is running.

    The sidecar is one caller of this endpoint; `curl` is another. Nothing on the delivery
    path touches the transport client, so an event posted by hand runs the same handler
    chain a delivered one does. These tests exist to keep that true -- the endpoint is the
    only way to exercise a handler without a broker, and every change to the delivery path
    so far has been able to break it.
    """

    @staticmethod
    def _app(dapr_eventing: DaprEventing) -> FastAPI:
        app = FastAPI()
        app.include_router(dapr_eventing.router)
        return app

    async def test_no_transport_client_is_needed(
        self, dapr_eventing: DaprEventing, mock_registry: MagicMock, cloud_event: CloudEvent, processed_result: ProcessingResult
    ) -> None:
        """on_startup never ran, so there is no DaprClient -- and the endpoint does not want one."""
        _wire_processing_result(mock_registry, processed_result)
        assert dapr_eventing._client is None

        async with AsyncClient(transport=ASGITransport(app=self._app(dapr_eventing)), base_url="http://local") as client:
            response = await client.post("/events/orders.created", json=dict(cloud_event))

        assert response.status_code == 200
        assert response.json() == {"status": "SUCCESS"}

    async def test_the_posted_event_reaches_the_handler_chain(
        self, dapr_eventing: DaprEventing, mock_registry: MagicMock, cloud_event: CloudEvent, processed_result: ProcessingResult
    ) -> None:
        _wire_processing_result(mock_registry, processed_result)

        async with AsyncClient(transport=ASGITransport(app=self._app(dapr_eventing)), base_url="http://local") as client:
            await client.post("/events/orders.created", json=dict(cloud_event))

        dispatched = mock_registry.get_service.return_value.process_event.await_args.args[0]
        assert dispatched.id == cloud_event.id
        assert dispatched.type == cloud_event.type

    async def test_the_topic_comes_from_the_url(
        self, dapr_eventing: DaprEventing, mock_registry: MagicMock, cloud_event: CloudEvent, processed_result: ProcessingResult
    ) -> None:
        """So posting to a different path exercises a different subscription's handlers."""
        _wire_processing_result(mock_registry, processed_result)

        async with AsyncClient(transport=ASGITransport(app=self._app(dapr_eventing)), base_url="http://local") as client:
            await client.post("/events/inventory.updated", json=dict(cloud_event))

        context = mock_registry.get_service.return_value.process_event.await_args.args[1]
        assert context["dapr_topic"] == "inventory.updated"

    async def test_a_handler_failure_is_reported_back_to_the_caller(
        self, dapr_eventing: DaprEventing, mock_registry: MagicMock, cloud_event: CloudEvent
    ) -> None:
        """Injecting by hand is only useful if the response says what the handler did."""
        mock_registry.get_service.return_value.process_event = AsyncMock(side_effect=InvalidEventError(status="error", reason="no payload"))
        mock_registry.correlation_context.set.return_value = MagicMock()

        async with AsyncClient(transport=ASGITransport(app=self._app(dapr_eventing)), base_url="http://local") as client:
            response = await client.post("/events/orders.created", json=dict(cloud_event))

        assert response.status_code == 200
        assert response.json() == {"status": "DROP", "reason": "no payload"}


class TestRestApiBaseRouteClass:
    """The route wrapper must stay scoped to the component that asks for it."""

    def test_dapr_eventing_uses_the_delivery_route(self, dapr_eventing: DaprEventing) -> None:
        assert all(isinstance(route, DaprDeliveryRoute) for route in dapr_eventing.router.routes)

    def test_other_components_keep_the_default_route(self, nats_eventing: NatsEventing) -> None:
        assert not any(isinstance(route, DaprDeliveryRoute) for route in nats_eventing.router.routes)

    async def test_an_ordinary_endpoint_still_answers_422(self, nats_eventing: NatsEventing) -> None:
        """422 is the right answer for a REST caller; only a Dapr delivery earns DROP."""
        app = FastAPI()
        app.include_router(nats_eventing.router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://caller") as client:
            response = await client.post("/events/orders.created", json={"not": "a cloud event"})

        assert response.status_code == 422


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
