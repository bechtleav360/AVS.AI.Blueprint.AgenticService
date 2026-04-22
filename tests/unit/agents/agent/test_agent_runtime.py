"""Unit tests for AgentRuntime."""

from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.agent.agent_runtime import AgentRuntime

# ---------------------------------------------------------------------------
# get_pydantic_name
# ---------------------------------------------------------------------------


class TestGetPydanticName:
    def test_returns_name(self, runtime: AgentRuntime) -> None:
        runtime._name = "my-agent"
        assert runtime.get_pydantic_name() == "my-agent"

    def test_returns_empty_string_when_name_is_none(self, runtime: AgentRuntime) -> None:
        runtime._name = None
        assert runtime.get_pydantic_name() == ""


# ---------------------------------------------------------------------------
# get_model_settings
# ---------------------------------------------------------------------------


class TestGetModelSettings:
    def test_returns_cached_settings_without_config_call(self, runtime: AgentRuntime, mock_config: MagicMock) -> None:
        runtime._model_settings = {"max_tokens": 500}
        settings = runtime.get_model_settings()
        assert settings == {"max_tokens": 500}
        mock_config.get_ai_config.assert_not_called()

    def test_reads_max_tokens_from_config(self, runtime: AgentRuntime, mock_config: MagicMock) -> None:
        mock_config.get_ai_config.return_value = MagicMock(max_tokens=1024, temperature=None)
        settings = runtime.get_model_settings()
        assert settings.get("max_tokens") == 1024
        assert "temperature" not in settings

    def test_reads_temperature_from_config(self, runtime: AgentRuntime, mock_config: MagicMock) -> None:
        mock_config.get_ai_config.return_value = MagicMock(max_tokens=None, temperature=0.5)
        settings = runtime.get_model_settings()
        assert settings.get("temperature") == pytest.approx(0.5)
        assert "max_tokens" not in settings

    def test_returns_empty_dict_on_config_exception(self, runtime: AgentRuntime, mock_config: MagicMock) -> None:
        mock_config.get_ai_config.side_effect = RuntimeError("config failure")
        assert runtime.get_model_settings() == {}

    def test_caches_result_after_first_call(self, runtime: AgentRuntime, mock_config: MagicMock) -> None:
        mock_config.get_ai_config.return_value = MagicMock(max_tokens=100, temperature=None)
        runtime.get_model_settings()
        runtime.get_model_settings()
        mock_config.get_ai_config.assert_called_once()


# ---------------------------------------------------------------------------
# get_prompt
# ---------------------------------------------------------------------------


class TestGetPrompt:
    def test_returns_cached_prompt_without_loading(self, runtime: AgentRuntime, mock_config: MagicMock) -> None:
        runtime._prompt_cache["my_prompt"] = "cached content"
        with patch("blueprint.agents.agent.agent_runtime.PromptLoader.load_prompt") as mock_load:
            result = runtime.get_prompt("my_prompt")
        assert result == "cached content"
        mock_load.assert_not_called()

    def test_loads_prompt_and_caches_it(self, runtime: AgentRuntime, mock_config: MagicMock) -> None:
        with patch(
            "blueprint.agents.agent.agent_runtime.PromptLoader.load_prompt",
            return_value="loaded content",
        ):
            result = runtime.get_prompt("my_prompt")

        assert result == "loaded content"
        assert runtime._prompt_cache["my_prompt"] == "loaded content"

    def test_file_not_found_propagates(self, runtime: AgentRuntime, mock_config: MagicMock) -> None:
        with patch(
            "blueprint.agents.agent.agent_runtime.PromptLoader.load_prompt",
            side_effect=FileNotFoundError("missing.prompt not found"),
        ):
            with pytest.raises(FileNotFoundError):
                runtime.get_prompt("missing")


# ---------------------------------------------------------------------------
# record_metrics
# ---------------------------------------------------------------------------


class TestRecordMetrics:
    def test_no_op_when_recorder_is_none(self, runtime: AgentRuntime) -> None:
        runtime._recorder = None
        runtime.record_metrics(MagicMock(), 100.0, "gpt-4o")  # must not raise

    def test_delegates_to_recorder_with_explicit_model_name(self, runtime: AgentRuntime) -> None:
        runtime._recorder = MagicMock()
        mock_result = MagicMock()
        runtime.record_metrics(mock_result, 100.0, "gpt-4o")
        runtime._recorder.record.assert_called_once_with(mock_result, 100.0, "gpt-4o")

    def test_resolves_model_name_from_model_attribute(self, runtime: AgentRuntime) -> None:
        runtime._recorder = MagicMock()
        runtime.model = MagicMock(model_name="gpt-4o-mini")
        mock_result = MagicMock()
        runtime.record_metrics(mock_result, 100.0)
        runtime._recorder.record.assert_called_once_with(mock_result, 100.0, "gpt-4o-mini")

    def test_falls_back_to_unknown_when_model_has_no_model_name(self, runtime: AgentRuntime) -> None:
        runtime._recorder = MagicMock()
        runtime.model = MagicMock(spec=[])  # no model_name attribute
        mock_result = MagicMock()
        runtime.record_metrics(mock_result, 100.0)
        runtime._recorder.record.assert_called_once_with(mock_result, 100.0, "unknown")


# ---------------------------------------------------------------------------
# on_startup / on_shutdown
# ---------------------------------------------------------------------------


class TestOnStartup:
    async def test_no_op_when_no_ai_client(self, runtime: AgentRuntime) -> None:
        runtime._ai_client = None
        await runtime.on_startup()  # must not raise

    async def test_creates_model_from_client(self, runtime: AgentRuntime) -> None:
        mock_model = MagicMock()
        mock_client = MagicMock()
        mock_client.create_model.return_value = mock_model
        runtime._ai_client = mock_client

        await runtime.on_startup()

        mock_client.create_model.assert_called_once()
        assert runtime.model is mock_model


# ---------------------------------------------------------------------------
# Deprecated methods
# ---------------------------------------------------------------------------


class TestDeprecatedMethods:
    async def test_run_with_prompt_raises_not_implemented(self, runtime: AgentRuntime) -> None:
        with pytest.raises(NotImplementedError):
            await runtime.run_with_prompt("prompt_name")

    def test_run_with_prompt_sync_raises_not_implemented(self, runtime: AgentRuntime) -> None:
        with pytest.raises(NotImplementedError):
            runtime.run_with_prompt_sync("prompt_name")
