"""Unit tests for AgentBuilder."""

from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel
from pydantic_ai import Tool

from base.src.agent.agent_builder import AgentBuilder
from base.src.config import Config


class TestAgentBuilder:
    """Test suite for AgentBuilder."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = Mock(spec=Config)
        config.get_ai_config.return_value = {
            "provider": "openai",
            "model_name": "gpt-4",
            "api_key": "test-key",
        }
        config.get_prompt_config.return_value = {
            "system_prompt_name": "test_prompt",
        }
        return config

    @pytest.fixture
    def builder(self, mock_config):
        """Create AgentBuilder instance."""
        return AgentBuilder(mock_config, runtime_name="test_runtime")

    def test_builder_initialization(self, mock_config):
        """Test AgentBuilder can be initialized."""
        builder = AgentBuilder(mock_config, runtime_name="test")

        assert builder._config == mock_config
        assert builder._runtime_name == "test"
        assert builder._model is None
        assert builder._system_prompt is None
        assert builder._tools == []

    def test_with_model_sets_model_name(self, builder, mock_config):
        """Test with_model configures model with specific name."""
        with patch(
            "base.src.agent.agent_builder.ModelProviderFactory.create_model"
        ) as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            result = builder.with_model("gpt-4-turbo")

            assert result == builder  # Fluent interface
            assert builder._model == mock_model
            mock_create.assert_called_once()

    def test_with_model_from_config_uses_runtime_config(self, builder, mock_config):
        """Test with_model_from_config loads model from configuration."""
        with patch(
            "base.src.agent.agent_builder.ModelProviderFactory.create_model"
        ) as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            result = builder.with_model_from_config()

            assert result == builder
            assert builder._model == mock_model
            mock_config.get_ai_config.assert_called_with("test_runtime")

    def test_with_model_from_config_custom_runtime(self, builder, mock_config):
        """Test with_model_from_config can use custom runtime name."""
        with patch(
            "base.src.agent.agent_builder.ModelProviderFactory.create_model"
        ) as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            result = builder.with_model_from_config("custom_runtime")

            assert result == builder
            mock_config.get_ai_config.assert_called_with("custom_runtime")

    def test_with_system_prompt_text_sets_prompt(self, builder):
        """Test with_system_prompt_text sets prompt directly."""
        prompt = "You are a helpful assistant"

        result = builder.with_system_prompt_text(prompt)

        assert result == builder
        assert builder._system_prompt == prompt

    def test_with_system_prompt_file_loads_from_file(self, builder, mock_config):
        """Test with_system_prompt_file loads prompt from file."""
        with patch(
            "base.src.agent.agent_builder.PromptLoader.load_prompt"
        ) as mock_load:
            mock_load.return_value = "Loaded prompt from file"

            result = builder.with_system_prompt_file("test_prompt")

            assert result == builder
            assert builder._system_prompt == "Loaded prompt from file"
            mock_load.assert_called_once()

    def test_with_tools_sets_tool_list(self, builder):
        """Test with_tools sets list of tools."""

        def test_tool():
            return "result"

        tools = [Tool(name="test_tool", function=test_tool)]

        result = builder.with_tools(tools)

        assert result == builder
        assert builder._tools == tools
        assert len(builder._tools) == 1

    def test_with_tool_adds_single_tool(self, builder):
        """Test with_tool adds a single tool."""

        def test_tool():
            return "result"

        result = builder.with_tool("test_tool", test_tool)

        assert result == builder
        assert len(builder._tools) == 1
        assert builder._tools[0].name == "test_tool"

    def test_with_result_type_sets_output_type(self, builder):
        """Test with_result_type sets the result type."""

        class CustomOutput(BaseModel):
            result: str

        result = builder.with_result_type(CustomOutput)

        assert result == builder
        assert builder._result_type == CustomOutput

    def test_with_deps_type_sets_dependencies_type(self, builder):
        """Test with_deps_type sets the dependencies type."""

        class CustomDeps(BaseModel):
            user_id: str

        result = builder.with_deps_type(CustomDeps)

        assert result == builder
        assert builder._deps_type == CustomDeps

    def test_build_requires_model(self, builder):
        """Test build raises error if model not configured."""
        builder.with_system_prompt_text("Test prompt")

        with pytest.raises(ValueError, match="Model must be configured"):
            builder.build()

    def test_build_requires_system_prompt(self, builder):
        """Test build raises error if system prompt not configured."""
        with patch(
            "base.src.agent.agent_builder.ModelProviderFactory.create_model"
        ) as mock_create:
            mock_create.return_value = Mock()
            builder.with_model("gpt-4")

        with pytest.raises(ValueError, match="System prompt must be configured"):
            builder.build()

    def test_build_creates_agent_with_all_config(self, builder, mock_config):
        """Test build creates agent with all configuration."""

        def test_tool():
            return "result"

        class CustomOutput(BaseModel):
            result: str

        with patch(
            "base.src.agent.agent_builder.ModelProviderFactory.create_model"
        ) as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            with patch("base.src.agent.agent_builder.Agent") as mock_agent_class:
                mock_agent = Mock()
                mock_agent_class.return_value = mock_agent

                agent = (
                    builder.with_model("gpt-4")
                    .with_system_prompt_text("Test prompt")
                    .with_tool("test_tool", test_tool)
                    .with_result_type(CustomOutput)
                    .build()
                )

                assert agent == mock_agent
                mock_agent_class.assert_called_once()
                call_kwargs = mock_agent_class.call_args[1]
                assert call_kwargs["model"] == mock_model
                assert call_kwargs["system_prompt"] == "Test prompt"
                assert call_kwargs["result_type"] == CustomOutput

    def test_fluent_interface_chaining(self, builder, mock_config):
        """Test builder methods can be chained fluently."""
        with patch(
            "base.src.agent.agent_builder.ModelProviderFactory.create_model"
        ) as mock_create:
            mock_create.return_value = Mock()

            with patch("base.src.agent.agent_builder.Agent"):
                # Should not raise error
                agent = (
                    builder.with_model("gpt-4")
                    .with_system_prompt_text("Test")
                    .with_tools([])
                    .build()
                )

                assert agent is not None

    def test_build_with_no_tools(self, builder, mock_config):
        """Test build works with no tools configured."""
        with patch(
            "base.src.agent.agent_builder.ModelProviderFactory.create_model"
        ) as mock_create:
            mock_create.return_value = Mock()

            with patch("base.src.agent.agent_builder.Agent") as mock_agent_class:
                mock_agent = Mock()
                mock_agent_class.return_value = mock_agent

                agent = (
                    builder.with_model("gpt-4")
                    .with_system_prompt_text("Test")
                    .build()
                )

                call_kwargs = mock_agent_class.call_args[1]
                assert call_kwargs["tools"] is None  # No tools

    def test_build_with_multiple_tools(self, builder, mock_config):
        """Test build works with multiple tools."""

        def tool1():
            return "1"

        def tool2():
            return "2"

        with patch(
            "base.src.agent.agent_builder.ModelProviderFactory.create_model"
        ) as mock_create:
            mock_create.return_value = Mock()

            with patch("base.src.agent.agent_builder.Agent") as mock_agent_class:
                mock_agent = Mock()
                mock_agent_class.return_value = mock_agent

                agent = (
                    builder.with_model("gpt-4")
                    .with_system_prompt_text("Test")
                    .with_tool("tool1", tool1)
                    .with_tool("tool2", tool2)
                    .build()
                )

                call_kwargs = mock_agent_class.call_args[1]
                assert len(call_kwargs["tools"]) == 2
