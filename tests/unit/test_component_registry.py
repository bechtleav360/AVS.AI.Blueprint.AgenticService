"""ComponentRegistry integration tests using real handler and runtime implementations."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import BaseModel

from blueprint.agents.config.config import Config
from blueprint.agents.base import EventHandler, BusinessService, RestApi, AgentRuntime
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.registry.component_registry import ComponentRegistry


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
        return {"handled_by": self._name, "source": event.source}


class ComponentRegistryRuntime:
    """Minimal runtime exposing configuration for registry interaction tests."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._name = self.__class__.__name__
        self._component_registry: ComponentRegistry | None = None
        self._processed_payloads: list[str] = []

    def get_name(self) -> str:
        """Get the component name."""
        return self._name

    def link_component_registry(self, registry: ComponentRegistry) -> None:
        """Link the component registry."""
        self._component_registry = registry

    def link_config(self, config: Config) -> None:
        """Link configuration."""
        self.config = config

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
        assert handlers[0]._name == "echo"
        assert handlers[0]._priority == 5

    def test_handlers_are_sorted_by_priority(self, registry: ComponentRegistry) -> None:
        registry.register_handler(EchoHandler(name="slow", priority=30))
        registry.register_handler(EchoHandler(name="fast", priority=10))
        registry.register_handler(EchoHandler(name="medium", priority=20))

        priorities = [handler._priority for handler in registry.get_handlers()]
        assert priorities == [10, 20, 30]

    def test_get_handlers_returns_copy(self, registry: ComponentRegistry) -> None:
        handler = EchoHandler(name="copy")
        registry.register_handler(handler)

        first = registry.get_handlers()
        second = registry.get_handlers()

        assert first == second
        assert first is not second

    def test_clear_handlers(self, registry: ComponentRegistry) -> None:
        registry.register_handler(EchoHandler(name="a"))
        registry.register_handler(EchoHandler(name="b"))
        assert registry.get_handlers()

        registry.clear_handlers()
        assert registry.get_handlers() == []

    def test_register_runtime_and_retrieve(self, registry: ComponentRegistry, config: Config) -> None:
        runtime = ComponentRegistryRuntime(config)
        registry.register_agent(runtime)

        assert registry.get_agent("ComponentRegistryRuntime") is runtime

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
        registry.register_agent(ComponentRegistryRuntime(registry.get_settings()))

        registry.clear()

        assert registry.get_handlers() == []
        assert registry.list_agents() == []

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

    def test_get_service_by_class(self, registry: ComponentRegistry) -> None:
        """Test retrieving a service by its class type."""

        class MockService(BusinessService):
            pass

        service = MockService(name="my_service")
        registry.register_service(service)

        retrieved = registry.get_service(MockService)
        assert retrieved is service

    def test_get_service_by_class_missing_raises(self, registry: ComponentRegistry) -> None:
        """Test retrieving a missing service by class type raises ValueError."""

        class MockService(BusinessService):
            pass

        with pytest.raises(ValueError, match="Business service of type 'MockService' not found"):
            registry.get_service(MockService)

    def test_get_agent_by_class(self, registry: ComponentRegistry, config: Config) -> None:
        """Test retrieving an agent by its class type."""

        class MockAgent(AgentRuntime):
            pass

        agent = MockAgent(config=config, runtime_name="MockAgent")
        registry.register_agent(agent)

        retrieved = registry.get_agent(MockAgent)
        assert retrieved is agent

    def test_get_agent_by_class_missing_raises(self, registry: ComponentRegistry) -> None:
        """Test retrieving a missing agent by class type raises ValueError."""

        class MockAgent(AgentRuntime):
            pass

        with pytest.raises(ValueError, match="Agent of type 'MockAgent' not found"):
            registry.get_agent(MockAgent)

    def test_get_rest_api_by_class_missing_raises(self, registry: ComponentRegistry) -> None:
        """Test retrieving a missing REST API by class type raises ValueError."""

        class MockPayload(BaseModel):
            pass

        class MockRestApi(RestApi[MockPayload]):
            pass

        with pytest.raises(ValueError, match="REST API of type 'MockRestApi' not found"):
            registry.get_rest_api(MockRestApi)

    def test_get_service_by_name_still_works(self, registry: ComponentRegistry) -> None:
        """Test that string-based service retrieval still works."""

        class MockService(BusinessService):
            pass

        service = MockService(name="my_service")
        registry.register_service(service)

        retrieved = registry.get_service("my_service")
        assert retrieved is service

    def test_get_agent_by_name_still_works(self, registry: ComponentRegistry, config: Config) -> None:
        """Test that string-based agent retrieval still works."""

        class MockAgent(AgentRuntime):
            pass

        agent = MockAgent(config=config, runtime_name="my_agent")
        registry.register_agent(agent)

        retrieved = registry.get_agent("my_agent")
        assert retrieved is agent
