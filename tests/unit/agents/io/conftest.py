"""Shared fixtures for all io unit tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.config import Config


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    """Reset shared Component class state after every test.

    Mirrors the pattern from clients/conftest.py — _ComponentMeta stores
    shared_config and shared_registry as class-level attributes and must be
    cleared between tests to prevent cross-test leakage.
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
    """Inject a MagicMock Config as the shared component config."""
    config = MagicMock(spec=Config)
    Component.configure(config)
    return config


@pytest.fixture
def mock_registry() -> MagicMock:
    """Inject a spec-constrained MagicMock Registry before any component is instantiated.

    Pre-setting shared_registry prevents Component.__init__ from creating a
    real Registry, which keeps tests that exercise registry-dependent paths
    (cache, eventing, scheduling) fully isolated from the real component graph.

    Using spec=Registry is required: _wire_routes iterates Component.__dict__
    and would encounter the stored mock.  A plain MagicMock has _route (returns
    an empty MagicMock), causing an unpacking error.  spec=Registry constrains
    the mock to Registry's interface, so hasattr(mock, '_route') returns False
    and _wire_routes skips it correctly.
    """
    registry = MagicMock(spec=Registry)
    Component.shared_registry = registry
    return registry
