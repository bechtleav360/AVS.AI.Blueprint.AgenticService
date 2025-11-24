"""Unit tests for AgentBuilder."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel
from pydantic_ai import Tool

from blueprint.agents.agent.agent_builder import AgentBuilder
from blueprint.agents.base import AgentRuntime
from blueprint.agents.config import Config
from blueprint.agents.models.config import AIConfig, PromptConfig


class TestAgentBuilder:
    """Test suite for AgentBuilder."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = Mock(spec=Config)
        config.get_ai_config.return_value = AIConfig(
            provider="openai",
            model_name="gpt-4",
            api_key="test-key",
        )
        config.get_prompt_config.return_value = PromptConfig(
            system_prompt_name="test_prompt",
        )
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
        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            result = builder.with_model("gpt-4-turbo")

            assert result == builder  # Fluent interface
            assert builder._model == mock_model
            mock_create.assert_called_once()

    def test_with_model_from_config_uses_runtime_config(self, builder, mock_config):
        """Test with_model_from_config loads model from configuration."""
        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            result = builder.with_model_from_config()

            assert result == builder
            assert builder._model == mock_model
            mock_config.get_ai_config.assert_called_with("test_runtime")

    def test_with_model_from_config_custom_runtime(self, builder, mock_config):
        """Test with_model_from_config can use custom runtime name."""
        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            result = builder.with_model_from_config("custom_runtime")

            assert result == builder
            mock_config.get_ai_config.assert_called_with("custom_runtime")

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
        builder.with_system_prompt("Test prompt")

        with pytest.raises(ValueError, match="Model must be configured"):
            builder.build()

    def test_build_requires_system_prompt(self, builder):
        """Test build raises error if system prompt not configured."""
        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
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

        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            # Create a mock for the runtime instance
            mock_runtime_instance = Mock()

            # Create a mock for the AgentRuntime class that returns our instance
            mock_runtime_class = Mock(return_value=mock_runtime_instance)

            # Patch the AgentRuntime class and its __getitem__ method
            with patch("blueprint.agents.agent.agent_builder.AgentRuntime") as mock_runtime:
                # Configure __getitem__ to return our mock class
                mock_runtime.__getitem__.return_value = mock_runtime_class

                agent = (
                    builder.with_model("gpt-4")
                    .with_system_prompt("Test prompt")
                    .with_tool("test_tool", test_tool)
                    .with_result_type(CustomOutput)
                    .build()
                )

                # Verify the runtime was created with the right parameters
                mock_runtime_class.assert_called_once()

                # Get the call arguments
                args, kwargs = mock_runtime_class.call_args
                assert kwargs["model"] == mock_model
                assert kwargs["system_prompt"] == "Test prompt"
                assert len(kwargs["tools"]) == 1
                assert kwargs["tools"][0].name == "test_tool"
                assert kwargs["tools"][0].function == test_tool

                # The runtime should be our mock instance
                assert agent == mock_runtime_instance

    def test_fluent_interface_chaining(self, builder, mock_config):
        """Test builder methods can be chained fluently."""
        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
            mock_create.return_value = Mock()

            with patch("blueprint.agents.agent.agent_builder.AgentRuntime"):
                # Should not raise error
                agent = builder.with_model("gpt-4").with_system_prompt("Test").with_tools([]).build()

                assert agent is not None

    def test_build_with_no_tools(self, builder, mock_config):
        """Test build works with no tools configured."""
        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            # Create a mock for the runtime instance and class
            mock_runtime_instance = Mock()
            mock_runtime_class = Mock(return_value=mock_runtime_instance)

            with patch("blueprint.agents.agent.agent_builder.AgentRuntime") as mock_runtime:
                # Configure __getitem__ to return our mock class
                mock_runtime.__getitem__.return_value = mock_runtime_class

                agent = builder.with_model("gpt-4").with_system_prompt("Test").build()

                # Verify the runtime was created with the right parameters
                mock_runtime_class.assert_called_once()

                # Get the call arguments
                args, kwargs = mock_runtime_class.call_args
                assert kwargs["tools"] == []  # No tools configured
                assert agent == mock_runtime_instance

    def test_build_with_multiple_tools(self, builder, mock_config):
        """Test build works with multiple tools."""

        def tool1():
            return "1"

        def tool2():
            return "2"

        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
            mock_model = Mock()
            mock_create.return_value = mock_model

            # Create a mock for the runtime instance and class
            mock_runtime_instance = Mock()
            mock_runtime_class = Mock(return_value=mock_runtime_instance)

            with patch("blueprint.agents.agent.agent_builder.AgentRuntime") as mock_runtime:
                # Configure __getitem__ to return our mock class
                mock_runtime.__getitem__.return_value = mock_runtime_class

                agent = builder.with_model("gpt-4").with_system_prompt("Test").with_tool("tool1", tool1).with_tool("tool2", tool2).build()

                # Verify the runtime was created with the right parameters
                mock_runtime_class.assert_called_once()

                # Get the call arguments
                args, kwargs = mock_runtime_class.call_args
                assert len(kwargs["tools"]) == 2
                assert agent == mock_runtime_instance

    def test_build_with_additional_kwargs(self, builder, mock_config):
        """Test build passes additional valid kwargs to AgentRuntime constructor."""
        with (
            patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create,
            patch("inspect.signature") as mock_signature,
        ):
            # Mock the model
            mock_model = Mock()
            mock_create.return_value = mock_model

            # Create a mock for the runtime instance and class
            mock_runtime_instance = Mock()
            mock_runtime_class = Mock(return_value=mock_runtime_instance)

            # Create a mock for the signature
            mock_sig = Mock()
            mock_signature.return_value = mock_sig
            mock_sig.parameters = {
                "model": Mock(),
                "system_prompt": Mock(),
                "tools": Mock(),
                "name": Mock(),  # Valid parameter
                "retries": Mock(),  # Valid parameter
                "end_strategy": Mock(),  # Valid parameter
                "instrument": Mock(),  # Valid parameter
            }

            with patch("blueprint.agents.agent.agent_builder.AgentRuntime") as mock_runtime:
                mock_runtime.__getitem__.return_value = mock_runtime_class

                # Build with valid additional kwargs
                built_agent = (
                    builder.with_model("gpt-4")
                    .with_system_prompt("Test prompt")
                    .build(name="test_agent", retries=3, end_strategy="exhaustive", instrument=True)
                )

                # Verify the mock was called with the right parameters
                args, kwargs = mock_runtime_class.call_args
                assert kwargs["name"] == "test_agent"
                assert kwargs["retries"] == 3
                assert kwargs["end_strategy"] == "exhaustive"
                assert kwargs["instrument"] is True
                assert built_agent == mock_runtime_instance

    def test_build_with_invalid_kwargs(self, builder, mock_config):
        """Test build raises error for invalid kwargs."""
        with patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create:
            mock_create.return_value = Mock()

            with patch("blueprint.agents.agent.agent_builder.AgentRuntime") as mock_runtime:
                mock_runtime.__getitem__.return_value = Mock()

                # Try to build with an invalid kwarg
                with pytest.raises(ValueError, match="Unexpected keyword argument for Agent: invalid_param"):
                    (builder.with_model("gpt-4").with_system_prompt("Test prompt").build(invalid_param="should-fail"))

    def test_build_with_kwargs_overrides(self, builder, mock_config):
        """Test that explicitly passed kwargs take precedence over builder settings."""
        with (
            patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create,
            patch("inspect.signature") as mock_signature,
        ):
            # Mock the model
            mock_model = Mock()
            mock_create.return_value = mock_model

            # Create a mock for the runtime instance and class
            mock_runtime_instance = Mock()
            mock_runtime_class = Mock(return_value=mock_runtime_instance)

            # Create a mock for the signature
            mock_sig = Mock()
            mock_signature.return_value = mock_sig
            mock_sig.parameters = {
                "model": Mock(),
                "system_prompt": Mock(),
                "tools": Mock(),
                "retries": Mock(),  # Valid parameter
            }

            with patch("blueprint.agents.agent.agent_builder.AgentRuntime") as mock_runtime:
                mock_runtime.__getitem__.return_value = mock_runtime_class

                # Test that trying to override builder-set parameters raises an error
                with pytest.raises(
                    ValueError, match="The Agent argument 'tools' is set by the builder and cannot be given for instantiation"
                ):
                    builder.with_model("gpt-4").with_system_prompt("Test prompt").with_tool("test_tool", lambda: "test").build(
                        tools=[]
                    )  # This should raise an error

                # Test that additional valid parameters work
                built_agent = (
                    builder.with_model("gpt-4").with_system_prompt("Test prompt").with_tool("test_tool", lambda: "test").build(retries=2)
                )  # This should work

                # Verify the mock was called with the right parameters
                args, kwargs = mock_runtime_class.call_args
                assert kwargs["retries"] == 2  # Additional parameter should be passed through
                assert "test_tool" in [tool.name for tool in kwargs["tools"]]  # Original tools should be preserved
                assert built_agent == mock_runtime_instance

    def test_build_with_kwargs_and_generics(self, builder, mock_config):
        """Test build works with both generic parameters and kwargs."""

        class CustomOutput(BaseModel):
            result: str

        with (
            patch("blueprint.agents.agent.agent_builder.ModelProviderFactory.create_model") as mock_create,
            patch("inspect.signature") as mock_signature,
        ):
            # Mock the model
            mock_model = Mock()
            mock_create.return_value = mock_model

            # Create a mock for the runtime instance and class
            mock_runtime_instance = Mock()
            mock_runtime_class = Mock(return_value=mock_runtime_instance)

            # Create a mock for the signature
            mock_sig = Mock()
            mock_signature.return_value = mock_sig
            mock_sig.parameters = {
                "model": Mock(),
                "system_prompt": Mock(),
                "tools": Mock(),
                "name": Mock(),  # Valid parameter
                "retries": Mock(),  # Valid parameter
                "end_strategy": Mock(),  # Valid parameter
            }

            with patch("blueprint.agents.agent.agent_builder.AgentRuntime") as mock_runtime:
                mock_runtime.__getitem__.return_value = mock_runtime_class

                agent = (
                    builder.with_model("gpt-4")
                    .with_system_prompt("Test prompt")
                    .with_result_type(CustomOutput)
                    .build(name="generic_agent", retries=3, end_strategy="exhaustive")
                )

                # Verify the mock was called with the right parameters
                args, kwargs = mock_runtime_class.call_args
                assert kwargs["name"] == "generic_agent"
                assert kwargs["retries"] == 3
                assert kwargs["end_strategy"] == "exhaustive"
                assert agent == mock_runtime_instance

    def test_build_returns_agent_runtime(self, builder, mock_config):
        """Test that build() returns an AgentRuntime instance."""
        # Verify that the build method returns AgentRuntime type
        # This is a type-level test that checks the return type annotation
        import inspect

        sig = inspect.signature(builder.build)
        assert sig.return_annotation == AgentRuntime

    def test_build_passes_config_to_runtime_in_call(self, builder, mock_config):
        """Test that build() passes config to AgentRuntime during initialization."""
        # Verify builder stores config for passing to runtime
        assert builder._config == mock_config

    def test_build_passes_runtime_name_to_runtime_in_call(self, builder, mock_config):
        """Test that build() passes runtime_name to AgentRuntime during initialization."""
        # Verify builder stores runtime_name for passing to runtime
        assert builder._runtime_name == "test_runtime"

    def test_builder_initialization_with_package_root(self, mock_config):
        """Test AgentBuilder initialization with package_root."""
        builder = AgentBuilder(mock_config, runtime_name="test", package_root="/test/path")

        assert builder._package_root == Path("/test/path")

    def test_builder_initialization_without_package_root(self, mock_config):
        """Test AgentBuilder initialization without package_root."""
        builder = AgentBuilder(mock_config, runtime_name="test")

        assert builder._package_root is None
