"""Shared fixtures for handler unit tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent


class StubHandler(EventHandlerBase):
    """Minimal concrete EventHandlerBase for testing."""

    def __init__(self, priority: int = 100, *, can_handle: bool = True, result=None) -> None:
        super().__init__(priority=priority)
        self._can_handle = can_handle
        self._result = result

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return self._can_handle

    async def handle_event(self, event: GenericCloudEvent, context: dict):
        return self._result


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    with patch(
        "blueprint.agents.component.registry.CorrelationContextProvider.get_correlation_context",
        return_value=MagicMock(),
    ):
        yield
    Component.shared_config = None
    Component.shared_registry = None


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock(spec=Config)
    Component.configure(config)
    return config


@pytest.fixture
def mock_registry() -> MagicMock:
    """spec=Registry prevents _wire_routes from treating the stored mock as a route carrier."""
    registry = MagicMock(spec=Registry)
    Component.shared_registry = registry
    return registry


@pytest.fixture
def cloud_event() -> GenericCloudEvent:
    """Minimal valid CloudEvent for handler tests."""
    return GenericCloudEvent(id="evt-001", type="test.event", source="test-source")
