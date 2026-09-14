"""Unit tests for EventPublishingService."""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.clients.io.io_client_base import IOClientBase
from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.models.config import EventPublishingConfig, TopicConfig
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.services.eventing.event_publishing_service import EventPublishingService

# ---------------------------------------------------------------------------
# on_startup / on_shutdown
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_resolves_client_from_registry(
        self, real_registry: Registry, mock_config: MagicMock, register_client: Callable[[str], MagicMock]
    ) -> None:
        mock_config.get_event_publishing_config.return_value = EventPublishingConfig()
        client = register_client("")
        svc = EventPublishingService()
        await svc.on_startup()
        assert svc._client is client

    async def test_on_startup_loads_pub_config(self, mock_registry: MagicMock, mock_config: MagicMock, mock_io_client: MagicMock) -> None:
        expected = EventPublishingConfig(topic_mapping={"x.event": TopicConfig(topic="t")})
        mock_config.get_event_publishing_config.return_value = expected
        mock_registry.get_io_clients.return_value = [mock_io_client]
        svc = EventPublishingService()
        await svc.on_startup()
        assert svc._pub_config is expected

    async def test_on_shutdown_is_noop(self, event_publishing_service: EventPublishingService) -> None:
        await event_publishing_service.on_shutdown()


# ---------------------------------------------------------------------------
# _get_pub_config
# ---------------------------------------------------------------------------


class TestGetPubConfig:
    def test_raises_when_not_started(self, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        svc = EventPublishingService()
        with pytest.raises(RuntimeError, match="on_startup"):
            svc._get_pub_config()

    def test_returns_config_when_set(
        self,
        event_publishing_service: EventPublishingService,
        pub_config: EventPublishingConfig,
    ) -> None:
        assert event_publishing_service._get_pub_config() is pub_config


# ---------------------------------------------------------------------------
# get_topic_for_event_type / get_available_event_types
# ---------------------------------------------------------------------------


class TestTopicLookup:
    def test_returns_topic_for_known_type(self, event_publishing_service: EventPublishingService) -> None:
        assert event_publishing_service.get_topic_for_event_type("test.event") == "test-topic"

    def test_returns_none_for_unknown_type(self, event_publishing_service: EventPublishingService) -> None:
        assert event_publishing_service.get_topic_for_event_type("unknown.event") is None

    def test_get_available_event_types_returns_all_keys(self, event_publishing_service: EventPublishingService) -> None:
        types = event_publishing_service.get_available_event_types()
        assert "test.event" in types
        assert "other.event" in types


# ---------------------------------------------------------------------------
# publish_event
# ---------------------------------------------------------------------------


class TestPublishEvent:
    async def test_calls_client_publish(
        self,
        event_publishing_service: EventPublishingService,
        mock_io_client: MagicMock,
        cloud_event: GenericCloudEvent,
    ) -> None:
        await event_publishing_service.publish_event(cloud_event)
        mock_io_client.publish.assert_awaited_once()

    async def test_resolves_topic_from_mapping(
        self,
        event_publishing_service: EventPublishingService,
        mock_io_client: MagicMock,
        cloud_event: GenericCloudEvent,
    ) -> None:
        await event_publishing_service.publish_event(cloud_event)
        topic_arg = mock_io_client.publish.call_args[0][0]
        assert topic_arg == "test-topic"

    async def test_returns_published_status(
        self,
        event_publishing_service: EventPublishingService,
        cloud_event: GenericCloudEvent,
    ) -> None:
        result = await event_publishing_service.publish_event(cloud_event)
        assert result["status"] == "published"

    async def test_result_contains_topic(
        self,
        event_publishing_service: EventPublishingService,
        cloud_event: GenericCloudEvent,
    ) -> None:
        result = await event_publishing_service.publish_event(cloud_event)
        assert result["topic"] == "test-topic"

    async def test_raises_when_no_mapping_and_no_explicit_topic(self, event_publishing_service: EventPublishingService) -> None:
        event = GenericCloudEvent(id="x", type="unmapped.event", source="src")
        with pytest.raises(ValueError, match="No topic mapping found"):
            await event_publishing_service.publish_event(event)

    async def test_explicit_topic_overrides_mapping(
        self,
        event_publishing_service: EventPublishingService,
        mock_io_client: MagicMock,
        cloud_event: GenericCloudEvent,
    ) -> None:
        await event_publishing_service.publish_event(cloud_event, topic="explicit-topic")
        topic_arg = mock_io_client.publish.call_args[0][0]
        assert topic_arg == "explicit-topic"

    async def test_sets_default_source_when_missing(
        self,
        event_publishing_service: EventPublishingService,
        mock_config: MagicMock,
    ) -> None:
        event = GenericCloudEvent(id="x", type="test.event")
        await event_publishing_service.publish_event(event)
        assert event.source is not None


# ---------------------------------------------------------------------------
# publish_handler_event
# ---------------------------------------------------------------------------


class TestPublishHandlerEvent:
    async def test_skips_when_no_topic_mapping(
        self,
        event_publishing_service: EventPublishingService,
        mock_io_client: MagicMock,
        cloud_event: GenericCloudEvent,
    ) -> None:
        await event_publishing_service.publish_handler_event(
            event_type="unmapped.event",
            data={},
            metadata={},
            source_event=cloud_event,
        )
        mock_io_client.publish.assert_not_awaited()

    async def test_skips_when_topic_matches_source_topic(
        self,
        event_publishing_service: EventPublishingService,
        mock_io_client: MagicMock,
    ) -> None:
        source = GenericCloudEvent(id="s", type="test.event", source="src", topic="test-topic")
        await event_publishing_service.publish_handler_event(
            event_type="test.event",
            data={},
            metadata={},
            source_event=source,
        )
        mock_io_client.publish.assert_not_awaited()

    async def test_publishes_when_mapping_found(
        self,
        event_publishing_service: EventPublishingService,
        mock_io_client: MagicMock,
        cloud_event: GenericCloudEvent,
    ) -> None:
        await event_publishing_service.publish_handler_event(
            event_type="other.event",
            data={"x": 1},
            metadata={},
            source_event=cloud_event,
        )
        mock_io_client.publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# publish_status_event
# ---------------------------------------------------------------------------


class TestPublishStatusEvent:
    async def test_type_format(
        self,
        event_publishing_service: EventPublishingService,
        mock_io_client: MagicMock,
    ) -> None:
        event_publishing_service._pub_config = EventPublishingConfig(
            topic_mapping={"agent.status.completed": TopicConfig(topic="status-topic")}
        )
        result = await event_publishing_service.publish_status_event({"done": True}, "completed")
        assert result["status"] == "published"

    async def test_delegates_to_publish_event(
        self,
        event_publishing_service: EventPublishingService,
        mock_io_client: MagicMock,
    ) -> None:
        event_publishing_service._pub_config = EventPublishingConfig(
            topic_mapping={"agent.status.started": TopicConfig(topic="status-topic")}
        )
        await event_publishing_service.publish_status_event({"key": "val"}, "started")
        mock_io_client.publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# P6 -- one publishing service per namespace, on its own client (spec sec. 6)
# ---------------------------------------------------------------------------


@pytest.fixture
def real_registry() -> Registry:
    """A real Registry, because what is under test is the resolution it performs.

    `EventPublishingService` no longer resolves its client by hand: `self.registry` is its
    namespace's view, and the view is what prefers this agent's transport over a root one. A
    MagicMock registry would only assert that a stub returned what it was told to.
    """
    registry = Registry(Component)
    Component.shared_registry = registry
    return registry


@pytest.fixture
def register_client(real_registry: Registry) -> Callable[[str], MagicMock]:
    """Register an IO client belonging to a namespace, named as Component would name it."""

    def _register(namespace: str, name: str = "nats_client") -> MagicMock:
        client = MagicMock(spec=IOClientBase)
        client.namespace = namespace
        client.publish = AsyncMock()
        real_registry.add_component(f"{namespace}_{name}" if namespace else name, client)
        return client

    return _register


class TestNamespaceOwnership:
    def test_default_is_the_root_namespace(self, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        assert EventPublishingService().namespace == ""

    def test_root_service_keeps_the_unqualified_registry_name(self, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        assert EventPublishingService().name == "event_publishing_service"

    def test_namespaced_service_registers_under_a_qualified_name(self, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        assert EventPublishingService(namespace="orders").name == "orders_event_publishing_service"

    async def test_publishes_on_its_own_namespaces_client(
        self, real_registry: Registry, mock_config: MagicMock, register_client: Callable[..., MagicMock]
    ) -> None:
        """Outbound traffic on another namespace's connection would be unattributable."""
        register_client("")
        own = register_client("orders")
        mock_config.get_event_publishing_config.return_value = EventPublishingConfig()

        svc = EventPublishingService(namespace="orders")
        await svc.on_startup()

        assert svc._client is own

    async def test_falls_back_to_the_root_client(
        self, real_registry: Registry, mock_config: MagicMock, register_client: Callable[..., MagicMock]
    ) -> None:
        """A namespaced agent in a process with one shared transport keeps working."""
        root = register_client("")
        register_client("invoice")
        mock_config.get_event_publishing_config.return_value = EventPublishingConfig()

        svc = EventPublishingService(namespace="orders")
        await svc.on_startup()

        assert svc._client is root

    async def test_never_borrows_another_namespaces_client(
        self, real_registry: Registry, mock_config: MagicMock, register_client: Callable[..., MagicMock]
    ) -> None:
        register_client("invoice")
        mock_config.get_event_publishing_config.return_value = EventPublishingConfig()

        svc = EventPublishingService(namespace="orders")
        with pytest.raises(ValueError, match="No IOClientBase is registered"):
            await svc.on_startup()

    async def test_two_clients_in_one_namespace_raise(
        self, real_registry: Registry, mock_config: MagicMock, register_client: Callable[..., MagicMock]
    ) -> None:
        register_client("orders", "nats_client")
        register_client("orders", "dapr_client")
        mock_config.get_event_publishing_config.return_value = EventPublishingConfig()

        svc = EventPublishingService(namespace="orders")
        with pytest.raises(ValueError, match="ambiguous"):
            await svc.on_startup()

    async def test_no_client_at_all_raises(self, real_registry: Registry, mock_config: MagicMock) -> None:
        mock_config.get_event_publishing_config.return_value = EventPublishingConfig()
        svc = EventPublishingService()
        with pytest.raises(ValueError, match="No components of type"):
            await svc.on_startup()
