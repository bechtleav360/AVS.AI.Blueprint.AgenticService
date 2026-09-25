"""Unit tests for NatsEventing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.io.api.eventing.nats import NATS_SUBJECT_CONTEXT_KEY, NatsEventing
from blueprint.agents.models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from blueprint.agents.models.events import CloudEvent


class TestNatsEventingPublish:
    async def test_publish_delegates_to_client(
        self,
        connected_nats_eventing: NatsEventing,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_nats_eventing.publish("events.topic", cloud_event)
        connected_nats_eventing._client.publish.assert_awaited_once()

    async def test_publish_passes_correct_topic_and_event(
        self,
        connected_nats_eventing: NatsEventing,
        cloud_event: CloudEvent,
    ) -> None:
        await connected_nats_eventing.publish("target.topic", cloud_event)
        args = connected_nats_eventing._client.publish.call_args[0]
        assert args[0] == "target.topic"
        assert args[1] is cloud_event

    async def test_publish_returns_success_message(
        self,
        connected_nats_eventing: NatsEventing,
        cloud_event: CloudEvent,
    ) -> None:
        result = await connected_nats_eventing.publish("topic", cloud_event)
        assert "message" in result

    async def test_publish_raises_when_client_none(
        self,
        nats_eventing: NatsEventing,
        cloud_event: CloudEvent,
    ) -> None:
        with pytest.raises(RuntimeError, match="NATS client not initialized"):
            await nats_eventing.publish("topic", cloud_event)


# ---------------------------------------------------------------------------
# on_startup — topic collection and client.subscribe() delegation
# ---------------------------------------------------------------------------


class TestNatsEventingPublishIsNotInjection:
    """On the NATS transport POST /events/{topic} publishes; it does not inject.

    Worth pinning down, because the same path on DaprEventing dispatches straight into the
    handler chain. Here the event goes to the broker and comes back through a subscription,
    so this endpoint needs a reachable NATS server -- it is not the no-broker escape hatch
    the Dapr one is.
    """

    async def test_the_event_goes_to_the_broker(self, connected_nats_eventing: NatsEventing, cloud_event: CloudEvent) -> None:
        await connected_nats_eventing.publish("orders.created", cloud_event)
        connected_nats_eventing._client.publish.assert_awaited_once_with("orders.created", cloud_event)

    async def test_the_handler_chain_is_not_called_directly(
        self, connected_nats_eventing: NatsEventing, mock_registry: MagicMock, cloud_event: CloudEvent
    ) -> None:
        await connected_nats_eventing.publish("orders.created", cloud_event)
        mock_registry.get_service.assert_not_called()

    async def test_without_a_client_it_says_so(self, nats_eventing: NatsEventing, cloud_event: CloudEvent) -> None:
        """A publish before on_startup has no broker connection to use."""
        with pytest.raises(RuntimeError, match="not initialized"):
            await nats_eventing.publish("orders.created", cloud_event)


class TestNatsEventingOnStartup:
    async def test_fetches_nats_client_from_registry(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = []
        mock_config.get_nats_subscription_config.return_value = []

        await nats_eventing.on_startup()

        assert nats_eventing._client is mock_client

    async def test_no_topics_skips_client_subscribe(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = []
        mock_config.get_nats_subscription_config.return_value = []

        await nats_eventing.on_startup()

        mock_client.subscribe.assert_not_called()

    async def test_handler_declared_topics_passed_to_client_subscribe(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["events.created"]
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = [handler]
        mock_config.get_nats_subscription_config.return_value = []

        await nats_eventing.on_startup()

        mock_client.subscribe.assert_awaited_once()
        mapping = mock_client.subscribe.call_args[0][0]
        assert "events.created" in mapping
        assert callable(mapping["events.created"])

    async def test_config_declared_topics_passed_to_client_subscribe(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = []
        mock_config.get_nats_subscription_config.return_value = ["orders.created", "orders.updated"]

        await nats_eventing.on_startup()

        mapping = mock_client.subscribe.call_args[0][0]
        assert set(mapping.keys()) == {"orders.created", "orders.updated"}

    async def test_duplicate_topic_appears_once_in_mapping(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["shared.topic"]
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = [handler]
        mock_config.get_nats_subscription_config.return_value = ["shared.topic", "other.topic"]

        await nats_eventing.on_startup()

        mapping = mock_client.subscribe.call_args[0][0]
        assert list(mapping.keys()).count("shared.topic") == 1
        assert "other.topic" in mapping

    async def test_handler_topics_precede_config_topics(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["handler.topic"]
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = [handler]
        mock_config.get_nats_subscription_config.return_value = ["config.topic"]

        await nats_eventing.on_startup()

        mapping = mock_client.subscribe.call_args[0][0]
        assert list(mapping.keys()) == ["handler.topic", "config.topic"]

    async def test_on_startup_returns_without_raising_when_client_subscribe_is_non_blocking(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        """on_startup must return immediately; subscribe() starts a background task."""
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["t"]
        mock_client = MagicMock()
        mock_client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = [handler]
        mock_config.get_nats_subscription_config.return_value = []

        await nats_eventing.on_startup()  # must not raise or hang


# ---------------------------------------------------------------------------
# the callback must let failures reach the transport (spec sec. 7.2)
# ---------------------------------------------------------------------------


class TestNatsEventingCallbackPropagatesFailures:
    """P2 -- catching here would acknowledge a failed event as processed."""

    @staticmethod
    def _callback(nats_eventing: NatsEventing, result_or_error) -> object:
        nats_eventing._process_cloud_event = AsyncMock(side_effect=result_or_error)  # type: ignore[method-assign]
        return nats_eventing._make_event_callback("orders.created")

    @pytest.mark.parametrize(
        "error",
        [
            RetryableHandlerError(status="e", reason="upstream down"),
            InvalidEventError(status="e", reason="no payload"),
            CriticalHandlerError(status="e", reason="corrupt state"),
            RuntimeError("boom"),
        ],
        ids=["retryable", "invalid", "critical", "unexpected"],
    )
    async def test_handler_errors_reach_the_caller(self, nats_eventing: NatsEventing, cloud_event: CloudEvent, error: Exception) -> None:
        callback = self._callback(nats_eventing, error)
        with pytest.raises(type(error)):
            await callback(cloud_event, "orders.created")

    async def test_successful_dispatch_returns_none(self, nats_eventing: NatsEventing, cloud_event: CloudEvent, processed_result) -> None:
        callback = self._callback(nats_eventing, None)
        nats_eventing._process_cloud_event = AsyncMock(return_value=processed_result)  # type: ignore[method-assign]
        assert await callback(cloud_event, "orders.created") is None


class TestNatsEventingDeliverySubject:
    """H1 -- the subject the broker delivered on reaches the handler context, beside the subscription."""

    async def test_the_context_carries_the_subject_and_the_subscription(
        self, nats_eventing: NatsEventing, cloud_event: CloudEvent, processed_result
    ) -> None:
        nats_eventing._process_cloud_event = AsyncMock(return_value=processed_result)  # type: ignore[method-assign]
        await nats_eventing._make_event_callback("t.*.risk.>")(cloud_event, "t.T1.risk.created")

        context = nats_eventing._process_cloud_event.await_args.args[1]
        assert context == {"nats_topic": "t.*.risk.>", NATS_SUBJECT_CONTEXT_KEY: "t.T1.risk.created"}

    async def test_the_event_cannot_supply_it(self, nats_eventing: NatsEventing, processed_result) -> None:
        """A publisher writes the event, including any extension it likes; it does not write the context."""
        spoofed = CloudEvent(id="e1", type="risk.created", source="publisher", tenantid="T2", nats_subject="t.T2.risk.created")
        nats_eventing._process_cloud_event = AsyncMock(return_value=processed_result)  # type: ignore[method-assign]
        await nats_eventing._make_event_callback("t.*.risk.>")(spoofed, "t.T1.risk.created")

        assert nats_eventing._process_cloud_event.await_args.args[1][NATS_SUBJECT_CONTEXT_KEY] == "t.T1.risk.created"


# ---------------------------------------------------------------------------
# A standalone agent logs what v0.8.1 logged
# ---------------------------------------------------------------------------


class TestStandaloneSubscriptionLines:
    @staticmethod
    def _wire(mock_registry: MagicMock, mock_config: MagicMock, topics: list[str]) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = topics
        client = MagicMock()
        client.subscribe = AsyncMock()
        mock_registry.get_component.return_value = client
        mock_registry.get_event_handler.return_value = [handler] if topics else []
        mock_config.get_nats_subscription_config.return_value = []

    async def test_one_line_per_topic(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._wire(mock_registry, mock_config, ["a.created", "b.created"])
        with caplog.at_level("INFO", logger="blueprint.agents.io.api.eventing.nats"):
            await nats_eventing.on_startup()
        assert caplog.messages == [
            "NatsEventing: auto-subscribed to topic 'a.created'",
            "NatsEventing: auto-subscribed to topic 'b.created'",
        ]

    async def test_no_topics(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._wire(mock_registry, mock_config, [])
        with caplog.at_level("INFO", logger="blueprint.agents.io.api.eventing.nats"):
            await nats_eventing.on_startup()
        assert caplog.messages == ["NatsEventing: no auto-subscriptions configured"]
