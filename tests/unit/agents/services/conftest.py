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
    Component.reset_shared_state()


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock(spec=Config)
    # A namespaced component reads through Config.for_namespace(); the mock stands in for
    # both the loader and its views, so a test controls one object rather than two.
    config.for_namespace.return_value = config
    Component.configure(config)
    return config


@pytest.fixture
def mock_registry() -> MagicMock:
    """spec=Registry prevents _wire_routes from treating the stored mock as a route carrier."""
    registry = MagicMock(spec=Registry)
    Component.shared_registry = registry
    return registry
