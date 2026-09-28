"""Shared fixtures for component unit tests."""

from collections.abc import Generator

import pytest
from unittest.mock import MagicMock, patch

from blueprint.agents.component.component import Component


class ConcreteComponent(Component):
    """Minimal concrete Component implementation for testing."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


@pytest.fixture
def concrete_component() -> ConcreteComponent:
    """Return a registered ConcreteComponent instance."""
    return ConcreteComponent()


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    """Reset shared class-level state and patch correlation context for every test.

    _ComponentMeta stores the config and registry as class-level attributes
    on Component. Without this reset, state leaks between tests.
    """
    with patch(
        "blueprint.agents.component.registry.CorrelationContextProvider.get_correlation_context",
        return_value=MagicMock(),
    ):
        yield
    Component.reset_shared_state()
