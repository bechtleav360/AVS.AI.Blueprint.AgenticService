"""Unit tests for ComponentRegistry."""

from unittest.mock import MagicMock, Mock

import pytest

from base.src.agent import BaseAgent, EventHandler
from base.src.config import Config
from base.src.models.events import CloudEvent
from base.src.registry.component_registry import ComponentRegistry


@pytest.fixture
def mock_config():
    """Provides mock configuration."""
    config = Mock(spec=Config)
    config.get.return_value = "test_value"
    return config


@pytest.fixture
def component_registry(mock_config):
    """Provides a ComponentRegistry instance."""
    return ComponentRegistry(settings=mock_config)


class MockHandler(EventHandler):
    """Mock handler for testing."""

    def __init__(self, name: str, priority: int = 100):
        super().__init__(name, priority)

    async def _can_handle(self, event: CloudEvent, context: dict) -> bool:
        return True

    async def _handle(self, event: CloudEvent, context: dict):
        return {"processed_by": self.name}


class MockRuntime(BaseAgent):
    """Mock runtime for testing."""

    def __init__(self, config: Config):
        self.config = config
        self._agent = None

    def _get_prompt_name(self) -> str:
        return "test"

    def _get_tools(self) -> list:
        return []

    async def custom_health_check(self) -> bool:
        return True

    async def process_request(self, context=None, **kwargs):
        return {"result": "processed"}


class TestComponentRegistry:
    """Tests for ComponentRegistry."""

    def test_initialization(self, mock_config):
        """Test registry initializes correctly."""
        registry = ComponentRegistry(settings=mock_config)
        assert registry._settings == mock_config
        assert registry._handlers == []
        assert registry._runtimes == {}
        assert registry._default_runtime is None

    def test_register_single_handler(self, component_registry):
        """Test registering a single handler."""
        handler = MockHandler("TestHandler", priority=10)
        component_registry.register_handler(handler)

        handlers = component_registry.get_handlers()
        assert len(handlers) == 1
        assert handlers[0].name == "TestHandler"
        assert handlers[0].priority == 10

    def test_register_multiple_handlers(self, component_registry):
        """Test registering multiple handlers."""
        handler1 = MockHandler("Handler1", priority=20)
        handler2 = MockHandler("Handler2", priority=10)
        handler3 = MockHandler("Handler3", priority=30)

        component_registry.register_handlers([handler1, handler2, handler3])

        handlers = component_registry.get_handlers()
        assert len(handlers) == 3
        # Should be sorted by priority
        assert handlers[0].name == "Handler2"  # priority 10
        assert handlers[1].name == "Handler1"  # priority 20
        assert handlers[2].name == "Handler3"  # priority 30

    def test_handlers_sorted_by_priority(self, component_registry):
        """Test that handlers are automatically sorted by priority."""
        handler1 = MockHandler("Handler1", priority=50)
        handler2 = MockHandler("Handler2", priority=10)
        handler3 = MockHandler("Handler3", priority=30)

        component_registry.register_handler(handler1)
        component_registry.register_handler(handler2)
        component_registry.register_handler(handler3)

        handlers = component_registry.get_handlers()
        assert handlers[0].priority == 10
        assert handlers[1].priority == 30
        assert handlers[2].priority == 50

    def test_get_handlers_returns_copy(self, component_registry):
        """Test that get_handlers returns a copy, not the original list."""
        handler = MockHandler("TestHandler")
        component_registry.register_handler(handler)

        handlers1 = component_registry.get_handlers()
        handlers2 = component_registry.get_handlers()

        assert handlers1 is not handlers2
        assert handlers1 == handlers2

    def test_clear_handlers(self, component_registry):
        """Test clearing all handlers."""
        handler1 = MockHandler("Handler1")
        handler2 = MockHandler("Handler2")
        component_registry.register_handlers([handler1, handler2])

        assert len(component_registry.get_handlers()) == 2

        component_registry.clear_handlers()
        assert len(component_registry.get_handlers()) == 0

    def test_register_runtime(self, component_registry, mock_config):
        """Test registering a runtime."""
        runtime = MockRuntime(mock_config)
        component_registry.register_runtime("TestRuntime", runtime)

        retrieved = component_registry.get_runtime("TestRuntime")
        assert retrieved == runtime

    def test_register_runtime_as_default(self, component_registry, mock_config):
        """Test registering a runtime as default."""
        runtime = MockRuntime(mock_config)
        component_registry.register_runtime("TestRuntime", runtime, is_default=True)

        # Should be retrievable by name
        assert component_registry.get_runtime("TestRuntime") == runtime
        # Should be retrievable as default
        assert component_registry.get_runtime() == runtime
        assert component_registry.get_default_runtime_name() == "TestRuntime"

    def test_first_runtime_becomes_default(self, component_registry, mock_config):
        """Test that first runtime automatically becomes default."""
        runtime1 = MockRuntime(mock_config)
        runtime2 = MockRuntime(mock_config)

        component_registry.register_runtime("Runtime1", runtime1)
        component_registry.register_runtime("Runtime2", runtime2)

        # First runtime should be default
        assert component_registry.get_default_runtime_name() == "Runtime1"
        assert component_registry.get_runtime() == runtime1

    def test_explicit_default_overrides_first(self, component_registry, mock_config):
        """Test that explicit default overrides first runtime."""
        runtime1 = MockRuntime(mock_config)
        runtime2 = MockRuntime(mock_config)

        component_registry.register_runtime("Runtime1", runtime1)
        component_registry.register_runtime("Runtime2", runtime2, is_default=True)

        # Second runtime should be default
        assert component_registry.get_default_runtime_name() == "Runtime2"
        assert component_registry.get_runtime() == runtime2

    def test_get_runtime_by_name(self, component_registry, mock_config):
        """Test retrieving runtime by specific name."""
        runtime1 = MockRuntime(mock_config)
        runtime2 = MockRuntime(mock_config)

        component_registry.register_runtime("Runtime1", runtime1)
        component_registry.register_runtime("Runtime2", runtime2)

        assert component_registry.get_runtime("Runtime1") == runtime1
        assert component_registry.get_runtime("Runtime2") == runtime2

    def test_get_runtime_returns_none_for_unknown(self, component_registry):
        """Test that get_runtime returns None for unknown runtime."""
        result = component_registry.get_runtime("NonExistent")
        assert result is None

    def test_get_runtime_returns_none_when_no_default(self, component_registry):
        """Test that get_runtime returns None when no default is set."""
        result = component_registry.get_runtime()
        assert result is None

    def test_get_all_runtimes(self, component_registry, mock_config):
        """Test retrieving all runtimes."""
        runtime1 = MockRuntime(mock_config)
        runtime2 = MockRuntime(mock_config)

        component_registry.register_runtime("Runtime1", runtime1)
        component_registry.register_runtime("Runtime2", runtime2)

        all_runtimes = component_registry.get_all_runtimes()
        assert len(all_runtimes) == 2
        assert "Runtime1" in all_runtimes
        assert "Runtime2" in all_runtimes
        assert all_runtimes["Runtime1"] == runtime1
        assert all_runtimes["Runtime2"] == runtime2

    def test_get_all_runtimes_returns_copy(self, component_registry, mock_config):
        """Test that get_all_runtimes returns a copy."""
        runtime = MockRuntime(mock_config)
        component_registry.register_runtime("TestRuntime", runtime)

        runtimes1 = component_registry.get_all_runtimes()
        runtimes2 = component_registry.get_all_runtimes()

        assert runtimes1 is not runtimes2
        assert runtimes1 == runtimes2

    def test_clear_runtimes(self, component_registry, mock_config):
        """Test clearing all runtimes."""
        runtime1 = MockRuntime(mock_config)
        runtime2 = MockRuntime(mock_config)

        component_registry.register_runtime("Runtime1", runtime1)
        component_registry.register_runtime("Runtime2", runtime2)

        assert len(component_registry.get_all_runtimes()) == 2
        assert component_registry.get_default_runtime_name() is not None

        component_registry.clear_runtimes()

        assert len(component_registry.get_all_runtimes()) == 0
        assert component_registry.get_default_runtime_name() is None

    def test_clear_all_components(self, component_registry, mock_config):
        """Test clearing all components (handlers and runtimes)."""
        handler = MockHandler("TestHandler")
        runtime = MockRuntime(mock_config)

        component_registry.register_handler(handler)
        component_registry.register_runtime("TestRuntime", runtime)

        assert len(component_registry.get_handlers()) == 1
        assert len(component_registry.get_all_runtimes()) == 1

        component_registry.clear()

        assert len(component_registry.get_handlers()) == 0
        assert len(component_registry.get_all_runtimes()) == 0

    def test_get_settings(self, component_registry, mock_config):
        """Test retrieving settings from registry."""
        settings = component_registry.get_settings()
        assert settings == mock_config

    def test_handler_links_to_registry(self, component_registry):
        """Test that handler is linked to registry on registration."""
        handler = MockHandler("TestHandler")
        component_registry.register_handler(handler)

        # Handler should have registry linked
        assert hasattr(handler, "_registry")
        assert handler._registry == component_registry

    def test_runtime_links_to_registry(self, component_registry, mock_config):
        """Test that runtime is linked to registry on registration."""
        runtime = MockRuntime(mock_config)
        component_registry.register_runtime("TestRuntime", runtime)

        # Runtime should have registry linked
        assert hasattr(runtime, "_service_registry")
        assert runtime._service_registry == component_registry
