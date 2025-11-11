"""ComponentRegistry integration tests using real handler and runtime implementations."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from base.src.config.config import Config
from base.src.handler.event_handler import EventHandler
from base.src.models.events import CloudEvent
from base.src.registry.component_registry import ComponentRegistry


@dataclass
class DummyProcessingService:
    """Lightweight processing service placeholder."""

    name: str = "processing"


@dataclass
class DummyEventPublishingService:
    """Lightweight event publishing service placeholder."""

    name: str = "event_publisher"


class EchoHandler(EventHandler):
    """Concrete handler that echoes the processed event."""

    def __init__(self, name: str, priority: int = 100):
        super().__init__(name=name, priority=priority)

    async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: CloudEvent, context: dict) -> dict:
        return {"handled_by": self.name, "source": event.source}


class ComponentRegistryRuntime:
    """Minimal runtime exposing configuration for registry interaction tests."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._service_registry: ComponentRegistry | None = None
        self._processed_payloads: list[str] = []

    def link_service_registry(self, registry: ComponentRegistry) -> None:
        self._service_registry = registry

    async def process_request(self, event: CloudEvent, context: dict | None = None) -> dict:
        payload = event.data or {}
        self._processed_payloads.append(payload.get("id", "unknown"))
        return {"status": "ok", "processed": payload}

    async def custom_health_check(self) -> bool:
        return True

    def get_processed_payloads(self) -> list[str]:
        return self._processed_payloads.copy()


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def registry(config: Config) -> ComponentRegistry:
    return ComponentRegistry(settings=config)


@pytest.fixture
def sample_event() -> CloudEvent:
    return CloudEvent(
        id="event-1",
        source="test-suite",
        type="com.test.event",
        specversion="1.0",
        data={"id": "payload-1", "value": 42},
    )


class TestComponentRegistry:
    """Integration-style tests covering concrete interactions in the registry."""

    def test_register_and_retrieve_handler(self, registry: ComponentRegistry) -> None:
        handler = EchoHandler(name="echo", priority=5)
        registry.register_handler(handler)

        handlers = registry.get_handlers()
        assert len(handlers) == 1
        assert handlers[0].name == "echo"
        assert handlers[0].priority == 5

    def test_handlers_are_sorted_by_priority(self, registry: ComponentRegistry) -> None:
        registry.register_handlers(
            [
                EchoHandler(name="slow", priority=30),
                EchoHandler(name="fast", priority=10),
                EchoHandler(name="medium", priority=20),
            ]
        )

        priorities = [handler.priority for handler in registry.get_handlers()]
        assert priorities == [10, 20, 30]

    def test_get_handlers_returns_copy(self, registry: ComponentRegistry) -> None:
        handler = EchoHandler(name="copy")
        registry.register_handler(handler)

        first = registry.get_handlers()
        second = registry.get_handlers()

        assert first == second
        assert first is not second

    def test_clear_handlers(self, registry: ComponentRegistry) -> None:
        registry.register_handlers([EchoHandler(name="a"), EchoHandler(name="b")])
        assert registry.get_handlers()

        registry.clear_handlers()
        assert registry.get_handlers() == []

    def test_register_runtime_and_retrieve(self, registry: ComponentRegistry, config: Config) -> None:
        runtime = ComponentRegistryRuntime(config)
        registry._agent_registry.register("runtime", runtime)  # type: ignore[attr-defined]

        assert registry.get_agent_registry().get("runtime") is runtime

    def test_processing_service_registration(self, registry: ComponentRegistry) -> None:
        processing = DummyProcessingService()
        registry.register_processing_service(processing)
        assert registry.get_processing_service() is processing

    def test_event_publishing_service_registration(self, registry: ComponentRegistry) -> None:
        publisher = DummyEventPublishingService()
        registry.register_event_publishing_service(publisher)
        assert registry.get_event_publishing_service() is publisher

    def test_clear_registry_resets_state(self, registry: ComponentRegistry) -> None:
        registry.register_handler(EchoHandler(name="cleanup"))
        registry.get_agent_registry().register("cleanup-runtime", ComponentRegistryRuntime(registry.get_settings()))

        registry.clear()

        assert registry.get_handlers() == []
        assert registry.get_agent_registry().list_agents() == []

    def test_handler_links_component_registry(self, registry: ComponentRegistry) -> None:
        handler = EchoHandler(name="link")
        registry.register_handler(handler)

        assert handler._component_registry is registry  # pylint: disable=protected-access

    def test_processing_service_missing_raises(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError):
            registry.get_processing_service()

    def test_event_publishing_service_missing_raises(self, registry: ComponentRegistry) -> None:
        with pytest.raises(ValueError):
            registry.get_event_publishing_service()
