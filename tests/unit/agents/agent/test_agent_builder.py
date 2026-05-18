"""Unit tests for AgentBuilder."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from blueprint.agents.agent.agent_builder import AgentBuilder


@pytest.fixture
def mock_ai_config() -> MagicMock:
    ai_config = MagicMock()
    ai_config.model_name = "gpt-4o"
    ai_config.provider = "openai"
    ai_config.max_tokens = None
    ai_config.temperature = None
    return ai_config


@pytest.fixture
def builder(mock_config: MagicMock, mock_ai_config: MagicMock) -> AgentBuilder:
    mock_config.get_ai_config.return_value = mock_ai_config
    return AgentBuilder(mock_config, runtime_name="test-agent")


@pytest.fixture
def builder_with_model(builder: AgentBuilder, mock_registry: MagicMock) -> AgentBuilder:
    builder.with_model_from_config()
    return builder


# ---------------------------------------------------------------------------
# with_model_from_config
# ---------------------------------------------------------------------------


class TestWithModelFromConfig:
    def test_raises_when_no_model_name(self, builder: AgentBuilder, mock_ai_config: MagicMock) -> None:
        mock_ai_config.model_name = ""
        with pytest.raises(ValueError, match="No model name"):
            builder.with_model_from_config()

    def test_raises_when_no_provider(self, builder: AgentBuilder, mock_ai_config: MagicMock) -> None:
        mock_ai_config.provider = ""
        with pytest.raises(ValueError, match="No provider"):
            builder.with_model_from_config()

    def test_raises_for_unsupported_provider(self, builder: AgentBuilder, mock_ai_config: MagicMock) -> None:
        mock_ai_config.provider = "unsupported"
        with pytest.raises(ValueError, match="Unsupported provider"):
            builder.with_model_from_config()

    def test_stores_ai_config_and_returns_self(self, builder: AgentBuilder, mock_ai_config: MagicMock) -> None:
        result = builder.with_model_from_config()
        assert builder._ai_config is mock_ai_config
        assert result is builder

    def test_deprecated_runtime_name_logs_warning(self, builder: AgentBuilder, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            builder.with_model_from_config(runtime_name="ignored")
        assert "Deprecation" in caplog.text


# ---------------------------------------------------------------------------
# Fluent setters
# ---------------------------------------------------------------------------


class TestFluentSetters:
    def test_with_system_prompt_stores_name(self, builder: AgentBuilder) -> None:
        result = builder.with_system_prompt("my_system")
        assert builder._system_prompt == "my_system"
        assert result is builder

    def test_with_system_prompt_none_defaults_to_system(self, builder: AgentBuilder) -> None:
        builder.with_system_prompt(None)
        assert builder._system_prompt == "system"

    def test_with_tools_replaces_list(self, builder: AgentBuilder) -> None:
        tools = [MagicMock(), MagicMock()]
        result = builder.with_tools(tools)
        assert builder._tools is tools
        assert result is builder

    def test_with_tool_appends(self, builder: AgentBuilder) -> None:
        def my_fn() -> str:
            """My tool function."""
            return "result"

        result = builder.with_tool("my_tool", my_fn)
        assert len(builder._tools) == 1
        assert result is builder

    def test_with_result_type_stores_type(self, builder: AgentBuilder) -> None:
        class MyResult(BaseModel):
            value: str

        result = builder.with_result_type(MyResult)
        assert builder._result_type is MyResult
        assert result is builder

    def test_with_metrics_disabled(self, builder: AgentBuilder) -> None:
        builder.with_metrics(False)
        assert builder._metrics_enabled is False

    def test_metrics_enabled_by_default(self, builder: AgentBuilder) -> None:
        assert builder._metrics_enabled is True


# ---------------------------------------------------------------------------
# get_model_settings
# ---------------------------------------------------------------------------


class TestGetModelSettings:
    def test_returns_max_tokens_when_set(self, builder: AgentBuilder, mock_ai_config: MagicMock) -> None:
        mock_ai_config.max_tokens = 1024
        settings = builder.get_model_settings()
        assert settings["max_tokens"] == 1024

    def test_returns_temperature_when_set(self, builder: AgentBuilder, mock_ai_config: MagicMock) -> None:
        mock_ai_config.temperature = 0.7
        settings = builder.get_model_settings()
        assert settings["temperature"] == pytest.approx(0.7)

    def test_omits_none_values(self, builder: AgentBuilder, mock_ai_config: MagicMock) -> None:
        mock_ai_config.max_tokens = None
        mock_ai_config.temperature = None
        assert builder.get_model_settings() == {}


# ---------------------------------------------------------------------------
# build — error paths
# ---------------------------------------------------------------------------


class TestBuild:
    def test_raises_when_model_not_configured(self, builder: AgentBuilder) -> None:
        with pytest.raises(ValueError, match="with_model_from_config"):
            builder.build()

    def test_raises_when_already_built(self, builder_with_model: AgentBuilder) -> None:
        builder_with_model._built = True
        with pytest.raises(RuntimeError, match="already been called"):
            builder_with_model.build()

    def test_build_requires_system_prompt(self, builder_with_model: AgentBuilder) -> None:
        builder_with_model._config.get_prompt_config.side_effect = RuntimeError("no prompt config")
        with patch.dict(
            "blueprint.agents.agent.agent_builder._CLIENT_MAP",
            {"openai": MagicMock(return_value=MagicMock())},
        ):
            with pytest.raises(ValueError, match="System prompt must be configured"):
                builder_with_model.build()

    def test_build_raises_for_conflicting_kwarg(self, builder_with_model: AgentBuilder) -> None:
        builder_with_model._system_prompt = "system"
        with patch.dict(
            "blueprint.agents.agent.agent_builder._CLIENT_MAP",
            {"openai": MagicMock(return_value=MagicMock())},
        ):
            with pytest.raises(ValueError, match="set by the builder"):
                builder_with_model.build(model="override-model")

    def test_build_raises_for_unknown_kwarg(self, builder_with_model: AgentBuilder) -> None:
        builder_with_model._system_prompt = "system"
        with patch.dict(
            "blueprint.agents.agent.agent_builder._CLIENT_MAP",
            {"openai": MagicMock(return_value=MagicMock())},
        ):
            with pytest.raises(ValueError, match="Unexpected keyword argument"):
                builder_with_model.build(completely_unknown_kwarg="foo")
