"""Generic unit tests for the agent runtime in `custom.src.agent.runtime`."""

from unittest.mock import MagicMock

import pytest
from base.src.config import Config

from custom.src.agent.runtime import AgentRuntime
from custom.src.models.processing import ProcessingContext
from custom.src.models.results import CustomAgentOutput


@pytest.fixture
def mock_settings():
    """Provides mock settings for the agent runtime."""
    settings = MagicMock(spec=Config)
    settings.get_ai_config.return_value = {
        "provider": "openai",
        "model_name": "gpt-4",
        "api_key": "mock_key",
    }
    return settings


class TestAgentRuntime:
    """Tests for the placeholder AgentRuntime to ensure its structure is valid."""

    def test_get_prompt_name_returns_string(self):
        """Ensures the prompt name is a non-empty string."""
        runtime = AgentRuntime.__new__(AgentRuntime)  # Create without calling __init__
        prompt_name = runtime._get_prompt_name()
        assert isinstance(prompt_name, str)
        assert prompt_name == "system"  # Should not be empty

    def test_get_tools_returns_list(self):
        """Ensures the tools are returned as a list."""
        runtime = AgentRuntime.__new__(AgentRuntime)  # Create without calling __init__
        tools = runtime._get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0  # Placeholder should have at least one tool

    def test_get_processing_context_type_returns_type(self):
        """Ensures a Pydantic model is returned for the context type."""
        runtime = AgentRuntime.__new__(AgentRuntime)  # Create without calling __init__
        context_type = runtime._get_processing_context_type()
        assert context_type == ProcessingContext

    def test_get_result_type_returns_type(self):
        """Ensures a Pydantic model is returned for the result type."""
        runtime = AgentRuntime.__new__(AgentRuntime)  # Create without calling __init__
        result_type = runtime._get_result_type()
        assert result_type == CustomAgentOutput

    @pytest.mark.asyncio
    async def test_custom_health_check_returns_bool(self):
        """Ensures the placeholder health check returns a boolean."""
        runtime = AgentRuntime.__new__(AgentRuntime)  # Create without calling __init__
        health = await runtime.custom_health_check()
        assert isinstance(health, bool)
        assert health is True
