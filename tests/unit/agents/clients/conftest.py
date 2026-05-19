"""Shared fixtures for all client unit tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.config import Config


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    """Reset shared Component class state after every test.

    Mirrors the pattern in tests/unit/agents/component/conftest.py:
    _ComponentMeta stores shared_config and shared_registry as class-level
    attributes, so they must be cleared to prevent cross-test leakage.
    """
    with patch(
        "blueprint.agents.component.registry.CorrelationContextProvider.get_correlation_context",
        return_value=MagicMock(),
    ):
        yield
    Component.shared_config = None
    Component.shared_registry = None


@pytest.fixture
def mock_config() -> MagicMock:
    """Inject a MagicMock Config as the shared component config.

    All client classes read configuration via self.config, which resolves
    to Component.shared_config. This fixture sets that up once per test.
    """
    config = MagicMock(spec=Config)
    Component.configure(config)
    return config
