"""Shared fixtures for agent unit tests."""

import contextvars
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.agent.agent_runtime import AgentRuntime
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
    registry = MagicMock(spec=Registry)
    Component.shared_registry = registry
    return registry


@pytest.fixture
def runtime(mock_config: MagicMock, mock_registry: MagicMock) -> AgentRuntime:
    """AgentRuntime created via object.__new__, bypassing pydantic_ai.Agent.__init__.

    Instance attributes are set directly so that the methods under test can run
    without triggering pydantic_ai or Component registration side-effects.
    """
    rt = object.__new__(AgentRuntime)
    rt._name = "test-agent"
    # pydantic_ai Agent.name calls self._override_name.get() (no default — raises LookupError if unset).
    # Setting it to None makes the property return self._name as the fallback.
    rt._override_name = contextvars.ContextVar("_override_name")
    rt._override_name.set(None)
    rt._ai_client = None
    rt._prompt_cache = {}
    rt._model_settings = {}
    rt._recorder = None
    return rt
