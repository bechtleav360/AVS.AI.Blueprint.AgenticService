"""Unit tests for configuration resolution with environment variables and runtime-specific overrides."""

import os
from unittest.mock import patch

import pytest

from blueprint.agents.config import Config


class TestConfigResolution:
    """Test suite for configuration resolution with model_* pattern."""

    @pytest.fixture
    def temp_settings_file(self, tmp_path):
        """Create a minimal settings.toml file for testing."""
        settings_content = """
[development]
app_name = "test-app"
app_port = 8000
app_environment = "development"
"""
        settings_file = tmp_path / "settings.toml"
        settings_file.write_text(settings_content)
        return settings_file

    def test_env_var_global_config(self, temp_settings_file):
        """Test that global environment variables are correctly resolved."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-global-key",
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
                "DYNACONF_MODEL_NAME": "default",
                "DYNACONF_MODEL_MAX_TOKENS": "3000",
                "DYNACONF_MODEL_TEMPERATURE": "0.1",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            ai_config = config.get_ai_config("default")

            assert ai_config.provider == "vllm"
            assert ai_config.api_key == "vllm-global-key"
            assert ai_config.model_name == "default"
            assert ai_config.base_url == "https://avs-vllm.q14.net/v1"
            assert ai_config.max_tokens == 3000
            assert ai_config.temperature == 0.1

    def test_env_var_runtime_override(self, temp_settings_file):
        """Test that runtime-specific environment variables override global ones."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-global-key",
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
                "DYNACONF_MODEL_NAME": "default",
                "DYNACONF_MODEL_MAX_TOKENS": "3000",
                "DYNACONF_MODEL_TEMPERATURE": "0.1",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-evaluator-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_NAME": "gpt-5-mini-2025-08-07",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            evaluator_config = config.get_ai_config("evaluator")

            # Should use runtime-specific environment variables
            assert evaluator_config.provider == "openai"
            assert evaluator_config.api_key == "openai-evaluator-key"
            assert evaluator_config.model_name == "gpt-5-mini-2025-08-07"
            # Should fall back to global environment variables
            assert evaluator_config.base_url == "https://avs-vllm.q14.net/v1"
            assert evaluator_config.max_tokens == 3000
            assert evaluator_config.temperature == 0.1

    def test_multiple_runtime_overrides(self, temp_settings_file):
        """Test that multiple runtimes can have different configurations."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-global-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-evaluator-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_NAME": "gpt-5-mini-2025-08-07",
                "DYNACONF_RUNTIMES__SEARCH__MODEL_PROVIDER": "vllm",
                "DYNACONF_RUNTIMES__SEARCH__MODEL_BASE_URL": "https://avs-embed.q14.net/v1",
                "DYNACONF_RUNTIMES__SEARCH__MODEL_NAME": "embedding-model",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            # Global default should use vLLM
            default_config = config.get_ai_config("default")
            assert default_config.provider == "vllm"
            assert default_config.api_key == "vllm-global-key"

            # Evaluator should use OpenAI
            evaluator_config = config.get_ai_config("evaluator")
            assert evaluator_config.provider == "openai"
            assert evaluator_config.api_key == "openai-evaluator-key"
            assert evaluator_config.model_name == "gpt-5-mini-2025-08-07"

            # Search should use vLLM with different base URL
            search_config = config.get_ai_config("search")
            assert search_config.provider == "vllm"
            assert search_config.api_key == "vllm-global-key"
            assert search_config.base_url == "https://avs-embed.q14.net/v1"
            assert search_config.model_name == "embedding-model"

    def test_api_key_not_mixed_between_runtimes(self, temp_settings_file):
        """Test that API keys are not mixed between runtimes (critical test for the bug fix)."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-global-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-evaluator-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_NAME": "gpt-5-mini-2025-08-07",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            evaluator_config = config.get_ai_config("evaluator")

            # This is the critical assertion - evaluator should NOT use the global vLLM key
            assert evaluator_config.api_key == "openai-evaluator-key"
            assert evaluator_config.api_key != "vllm-global-key"
            assert evaluator_config.provider == "openai"

    def test_runtime_config_merging(self, temp_settings_file):
        """Test that get_runtime_config correctly merges global and runtime-specific settings."""
        config = Config(
            settings_files=[str(temp_settings_file)],
            root_path=temp_settings_file.parent,
        )

        runtime_config = config.get_runtime_config("evaluator")

        # Should have global defaults
        assert "model_provider" in runtime_config
        assert "model_base_url" in runtime_config
        assert "model_name" in runtime_config
        assert "model_max_tokens" in runtime_config
        assert "model_temperature" in runtime_config

        # Should have runtime-specific overrides
        assert runtime_config["model_provider"] == "openai"
        assert runtime_config["model_name"] == "gpt-4"

    def test_env_var_precedence_order(self, temp_settings_file):
        """Test the precedence order: runtime-specific env vars > global env vars > settings file."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-key",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            evaluator_config = config.get_ai_config("evaluator")

            # Runtime-specific env var should take precedence
            assert evaluator_config.api_key == "openai-key"

            default_config = config.get_ai_config("default")
            # Global env var should be used for default
            assert default_config.api_key == "vllm-key"

    def test_missing_runtime_uses_global_defaults(self, temp_settings_file):
        """Test that missing runtime configuration falls back to global defaults."""
        config = Config(
            settings_files=[str(temp_settings_file)],
            root_path=temp_settings_file.parent,
        )

        # Request a runtime that doesn't have specific config
        unknown_config = config.get_ai_config("unknown_runtime")

        # Should use global defaults
        assert unknown_config.provider == "vllm"
        assert unknown_config.model_name == "default"
        assert unknown_config.base_url == "https://avs-vllm.q14.net/v1"
        assert unknown_config.max_tokens == 3000
        assert unknown_config.temperature == 0.1

    def test_realistic_scenario(self, temp_settings_file):
        """Test a realistic scenario matching the user's deployment configuration."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-key",
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
                "DYNACONF_MODEL_MAX_TOKENS": "3000",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_NAME": "gpt-4",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            # Global vLLM configuration
            default_config = config.get_ai_config("default")
            assert default_config.provider == "vllm"
            assert default_config.api_key == "vllm-key"
            assert default_config.base_url == "https://avs-vllm.q14.net/v1"

            # Evaluator with OpenAI override
            evaluator_config = config.get_ai_config("evaluator")
            assert evaluator_config.provider == "openai"
            assert evaluator_config.api_key == "openai-key"
            assert evaluator_config.model_name == "gpt-4"
            # Should NOT use the global vLLM base URL for OpenAI
            assert evaluator_config.base_url == "https://avs-vllm.q14.net/v1"

            # Verify the critical fix: evaluator uses its own API key, not the global one
            assert evaluator_config.api_key != default_config.api_key
