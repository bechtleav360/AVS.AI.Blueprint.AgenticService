"""Shared fixtures for all services unit tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.config import Config


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
