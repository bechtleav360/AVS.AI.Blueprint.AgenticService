"""Unit tests for NatsEventing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.io.api.eventing.nats import NatsEventing
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
