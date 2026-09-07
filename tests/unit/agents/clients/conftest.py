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
    _ComponentMeta stores the config and registry as class-level
    attributes, so they must be cleared to prevent cross-test leakage.
    """
    with patch(
        "blueprint.agents.component.registry.CorrelationContextProvider.get_correlation_context",
        return_value=MagicMock(),
    ):
        yield
    Component.reset_shared_state()


@pytest.fixture
def mock_config() -> MagicMock:
    """Inject a MagicMock Config as the shared component config.

    All client classes read configuration via self.config, which resolves
    to Component._shared_config. This fixture sets that up once per test.
    """
    config = MagicMock(spec=Config)
    # A namespaced component reads through Config.for_namespace(); the mock stands in for
    # both the loader and its views, so a test controls one object rather than two.
    config.for_namespace.return_value = config
    Component.configure(config)
    return config
