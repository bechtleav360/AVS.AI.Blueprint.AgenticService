"""Shared fixtures for app_builder unit tests."""

import types
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent


class StubHandler(EventHandlerBase):
    """Minimal concrete EventHandlerBase for app_builder tests."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict):
        return None


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
    registry = MagicMock(spec=Registry)
    Component.shared_registry = registry
    return registry


@pytest.fixture
def builder(mock_config: MagicMock) -> AppBuilder:
    """AppBuilder with shared_config pre-configured — for fluent-setter tests."""
    return AppBuilder(mock_config)


@pytest.fixture
def build_config() -> MagicMock:
    """Config for build() tests — NOT pre-configured in Component.shared_config.

    build() calls Component.configure(self._config) internally; injecting via
    mock_config first would make that call raise 'already configured'.
    """
    config = MagicMock(spec=Config)
    config.get.return_value = ""  # safe default for all config.get() calls
    return config


@pytest.fixture
def builder_for_build(build_config: MagicMock, mock_registry: MagicMock) -> AppBuilder:
    """AppBuilder ready for build() — shared_config is still None."""
    return AppBuilder(build_config)


@pytest.fixture
def all_build_mocks():
    """Patch every Component constructor and FastAPI that build() creates.

    Yields a SimpleNamespace with one attribute per mock so tests can assert
    on specific constructors without relying on positional call ordering.
    """
    with (
        patch("blueprint.agents.app_builder.EventProcessingService") as eps,
        patch("blueprint.agents.app_builder.EventPublishingService") as epubs,
        patch("blueprint.agents.app_builder.ActuatorApi") as actuator,
        patch("blueprint.agents.app_builder.ClientHealthChecker") as checker,
        patch("blueprint.agents.app_builder.DaprClient") as dapr_client,
        patch("blueprint.agents.app_builder.DaprEventing") as dapr_eventing,
        patch("blueprint.agents.app_builder.NATSClient") as nats_client,
        patch("blueprint.agents.app_builder.NatsEventing") as nats_eventing,
        patch("blueprint.agents.app_builder.RootApi") as root_api,
        patch("blueprint.agents.app_builder.CacheManagementApi") as cache_api,
        patch("blueprint.agents.app_builder.FastAPI") as fastapi,
    ):
        yield types.SimpleNamespace(
            eps=eps,
            epubs=epubs,
            actuator=actuator,
            checker=checker,
            dapr_client=dapr_client,
            dapr_eventing=dapr_eventing,
            nats_client=nats_client,
            nats_eventing=nats_eventing,
            root_api=root_api,
            cache_api=cache_api,
            fastapi=fastapi,
        )


def wire_empty_registry(mock_registry: MagicMock) -> None:
    """Set all registry collection methods to return empty lists/False."""
    mock_registry.get_event_handler.return_value = []
    mock_registry.get_io_clients.return_value = []
    mock_registry.get_clients.return_value = []
    mock_registry.get_rest_apis.return_value = []
    mock_registry.has_cache.return_value = False
