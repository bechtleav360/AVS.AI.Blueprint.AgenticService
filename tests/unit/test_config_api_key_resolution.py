"""Unit tests for API key configuration resolution - validates the bug fix.

This test suite validates that runtime-specific API keys are correctly resolved
and do not fall back to global API keys when explicitly configured.
"""

import os
from unittest.mock import patch

import pytest

from blueprint.agents.config import Config


class TestAPIKeyResolution:
    """Test suite for API key resolution with runtime-specific overrides."""

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

    def test_runtime_specific_api_key_overrides_global(self, temp_settings_file):
        """Test that runtime-specific API key overrides global API key (CRITICAL BUG FIX).

        This is the core test for the bug fix. The evaluator runtime should use its own
        OpenAI API key, not the global vLLM API key.
        """
        with patch.dict(
            os.environ,
            {
                # Global vLLM configuration
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-global-key-12345",
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
                # Runtime-specific OpenAI configuration
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-evaluator-key-67890",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_NAME": "gpt-4",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            # Get evaluator configuration
            evaluator_config = config.get_ai_config("evaluator")

            # CRITICAL ASSERTION: evaluator should use its own API key, not the global one
            assert evaluator_config.api_key == "openai-evaluator-key-67890", "Evaluator should use runtime-specific OpenAI API key"
            assert evaluator_config.api_key != "vllm-global-key-12345", "Evaluator should NOT use global vLLM API key"
            assert evaluator_config.provider == "openai", "Evaluator should use OpenAI provider"

    def test_global_api_key_used_for_default_runtime(self, temp_settings_file):
        """Test that global API key is used for default runtime when no override exists."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-global-key-12345",
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            # Get default configuration
            default_config = config.get_ai_config("default")

            # Default should use global API key
            assert default_config.api_key == "vllm-global-key-12345", "Default runtime should use global API key"
            assert default_config.provider == "vllm", "Default runtime should use vLLM provider"

    def test_multiple_runtimes_with_different_api_keys(self, temp_settings_file):
        """Test that multiple runtimes can have different API keys without mixing."""
        with patch.dict(
            os.environ,
            {
                # Global vLLM
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-global-key",
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
                # Evaluator with OpenAI
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-evaluator-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_NAME": "gpt-4",
                # Search with different vLLM endpoint
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

            # Default should use global vLLM key
            default_config = config.get_ai_config("default")
            assert default_config.api_key == "vllm-global-key"
            assert default_config.provider == "vllm"

            # Evaluator should use its own OpenAI key
            evaluator_config = config.get_ai_config("evaluator")
            assert evaluator_config.api_key == "openai-evaluator-key"
            assert evaluator_config.provider == "openai"
            assert evaluator_config.model_name == "gpt-4"

            # Search should use global vLLM key (no override)
            search_config = config.get_ai_config("search")
            assert search_config.api_key == "vllm-global-key"
            assert search_config.provider == "vllm"
            assert search_config.base_url == "https://avs-embed.q14.net/v1"

            # Verify no API key mixing
            assert evaluator_config.api_key != default_config.api_key
            assert evaluator_config.api_key != search_config.api_key

    def test_runtime_config_merging_with_model_pattern(self, temp_settings_file):
        """Test that get_runtime_config correctly merges global and runtime-specific settings."""
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

            # Get runtime config for evaluator
            runtime_config = config.get_runtime_config("evaluator")

            # Should have global defaults merged in
            assert "model_provider" in runtime_config
            assert "model_api_key" in runtime_config
            assert "model_base_url" in runtime_config
            assert "model_max_tokens" in runtime_config

            # Should have runtime-specific overrides
            assert runtime_config["model_provider"] == "openai"
            assert runtime_config["model_api_key"] == "openai-key"
            assert runtime_config["model_name"] == "gpt-4"

            # Should have global fallbacks for non-overridden values
            assert runtime_config["model_base_url"] == "https://avs-vllm.q14.net/v1"
            assert runtime_config["model_max_tokens"] == 3000

    def test_missing_runtime_uses_global_defaults(self, temp_settings_file):
        """Test that missing runtime configuration falls back to global defaults."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "vllm-key",
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            # Request a runtime that doesn't have specific config
            unknown_config = config.get_ai_config("unknown_runtime")

            # Should use global defaults
            assert unknown_config.provider == "vllm"
            assert unknown_config.api_key == "vllm-key"
            assert unknown_config.base_url == "https://avs-vllm.q14.net/v1"

    def test_realistic_deployment_scenario(self, temp_settings_file):
        """Test realistic deployment scenario matching user's configuration.

        This test simulates the actual deployment where:
        - Global vLLM is configured for most runtimes
        - Evaluator runtime is overridden to use OpenAI
        """
        with patch.dict(
            os.environ,
            {
                # Global vLLM configuration
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "6FEDGzTQd8Oea8OO4onA",  # vLLM key
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
                "DYNACONF_MODEL_NAME": "default",
                "DYNACONF_MODEL_MAX_TOKENS": "3000",
                "DYNACONF_MODEL_TEMPERATURE": "0.1",
                # Evaluator OpenAI override
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "sk-svcacct-evaluator-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_NAME": "gpt-5-mini-2025-08-07",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(temp_settings_file)],
                root_path=temp_settings_file.parent,
            )

            # Verify global vLLM config
            default_config = config.get_ai_config("default")
            assert default_config.provider == "vllm"
            assert default_config.api_key == "6FEDGzTQd8Oea8OO4onA"
            assert default_config.model_name == "default"

            # Verify evaluator OpenAI config
            evaluator_config = config.get_ai_config("evaluator")
            assert evaluator_config.provider == "openai"
            assert evaluator_config.api_key == "sk-svcacct-evaluator-key"
            assert evaluator_config.model_name == "gpt-5-mini-2025-08-07"

            # CRITICAL: Verify no API key mixing
            assert evaluator_config.api_key != default_config.api_key, "BUG: Evaluator is using vLLM API key instead of OpenAI API key!"
