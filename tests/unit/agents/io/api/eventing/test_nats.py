"""Unit tests for NatsEventing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blueprint.agents.io.api.eventing.nats import NatsEventing
from blueprint.agents.models.events import CloudEvent


class TestNatsEventingSubscribe:
    async def test_subscribe_delegates_to_client(self, connected_nats_eventing: NatsEventing) -> None:
        await connected_nats_eventing.subscribe("events.topic")
        connected_nats_eventing._client.subscribe.assert_awaited_once()

    async def test_subscribe_passes_correct_topic(self, connected_nats_eventing: NatsEventing) -> None:
        await connected_nats_eventing.subscribe("my.topic")
        topic_arg = connected_nats_eventing._client.subscribe.call_args[0][0]
        assert topic_arg == "my.topic"

    async def test_subscribe_returns_success_message(self, connected_nats_eventing: NatsEventing) -> None:
        result = await connected_nats_eventing.subscribe("topic")
        assert "Subscribed" in result["message"] or "topic" in result["message"]

    async def test_subscribe_raises_when_client_none(self, nats_eventing: NatsEventing) -> None:
        with pytest.raises(RuntimeError, match="NATS client not initialized"):
            await nats_eventing.subscribe("topic")


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
# on_startup — auto-subscription logic
# ---------------------------------------------------------------------------


class TestNatsEventingConnectAndSubscribe:
    async def test_fetches_nats_client_from_registry(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_registry.get_component.return_value = mock_client
        mock_registry.get_event_handler.return_value = []
        mock_config.get_nats_subscription_config.return_value = []

        await nats_eventing._connect_and_subscribe()

        assert nats_eventing._client is mock_client

    async def test_no_topics_skips_subscribing(self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        mock_registry.get_component.return_value = MagicMock()
        mock_registry.get_event_handler.return_value = []
        mock_config.get_nats_subscription_config.return_value = []
        mock_sub = AsyncMock()
        with patch.object(nats_eventing, "_subscribe_to_topic", mock_sub):
            await nats_eventing._connect_and_subscribe()

        mock_sub.assert_not_called()

    async def test_handler_declared_topics_are_subscribed(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["events.created"]
        mock_registry.get_component.return_value = MagicMock()
        mock_registry.get_event_handler.return_value = [handler]
        mock_config.get_nats_subscription_config.return_value = []
        mock_sub = AsyncMock()
        with patch.object(nats_eventing, "_subscribe_to_topic", mock_sub):
            await nats_eventing._connect_and_subscribe()

        mock_sub.assert_awaited_once_with("events.created")

    async def test_config_declared_topics_are_subscribed(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        mock_registry.get_component.return_value = MagicMock()
        mock_registry.get_event_handler.return_value = []
        mock_config.get_nats_subscription_config.return_value = ["orders.created", "orders.updated"]
        mock_sub = AsyncMock()
        with patch.object(nats_eventing, "_subscribe_to_topic", mock_sub):
            await nats_eventing._connect_and_subscribe()

        assert mock_sub.await_count == 2

    async def test_duplicate_topic_subscribed_only_once(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["shared.topic"]
        mock_registry.get_component.return_value = MagicMock()
        mock_registry.get_event_handler.return_value = [handler]
        mock_config.get_nats_subscription_config.return_value = ["shared.topic", "other.topic"]
        mock_sub = AsyncMock()
        with patch.object(nats_eventing, "_subscribe_to_topic", mock_sub):
            await nats_eventing._connect_and_subscribe()

        subscribed = [c.args[0] for c in mock_sub.call_args_list]
        assert subscribed.count("shared.topic") == 1
        assert "other.topic" in subscribed

    async def test_handler_topics_precede_config_topics(
        self, nats_eventing: NatsEventing, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        handler = MagicMock()
        handler.get_subscribed_topics.return_value = ["handler.topic"]
        mock_registry.get_component.return_value = MagicMock()
        mock_registry.get_event_handler.return_value = [handler]
        mock_config.get_nats_subscription_config.return_value = ["config.topic"]
        mock_sub = AsyncMock()
        with patch.object(nats_eventing, "_subscribe_to_topic", mock_sub):
            await nats_eventing._connect_and_subscribe()

        subscribed = [c.args[0] for c in mock_sub.call_args_list]
        assert subscribed == ["handler.topic", "config.topic"]


# ---------------------------------------------------------------------------
# _subscribe_to_topic — client guard and delegation
# ---------------------------------------------------------------------------


class TestSubscribeToTopic:
    async def test_raises_when_client_is_none(self, nats_eventing: NatsEventing) -> None:
        with pytest.raises(RuntimeError, match="NATS client not initialized"):
            await nats_eventing._subscribe_to_topic("events.topic")

    async def test_calls_client_subscribe_with_topic_and_callback(self, connected_nats_eventing: NatsEventing) -> None:
        await connected_nats_eventing._subscribe_to_topic("test.topic")

        connected_nats_eventing._client.subscribe.assert_awaited_once()
        call_args = connected_nats_eventing._client.subscribe.call_args[0]
        assert call_args[0] == "test.topic"
        assert callable(call_args[1])
