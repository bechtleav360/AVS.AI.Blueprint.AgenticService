"""Unit tests for runtime-specific API key resolution.

This test validates the critical bug fix where runtime-specific API keys
must not fall back to global API keys when explicitly configured.
"""

import os
from unittest.mock import patch

import pytest

from blueprint.agents.config import Config


class TestRuntimeAPIKeyResolution:
    """Test suite validating the API key resolution bug fix."""

    @pytest.fixture
    def minimal_settings(self, tmp_path):
        """Create minimal settings.toml for testing."""
        settings_file = tmp_path / "settings.toml"
        settings_file.write_text(
            """
[development]
app_name = "test-app"
app_port = 8000
app_environment = "development"
"""
        )
        return settings_file

    def test_runtime_api_key_overrides_global_via_env_vars(self, minimal_settings):
        """Test that runtime-specific API key from env var overrides global key.

        This is the CRITICAL test for the bug fix. When both global and
        runtime-specific API keys are set via environment variables, the
        runtime-specific key should be used, not the global one.
        """
        with patch.dict(
            os.environ,
            {
                # Global vLLM API key
                "DYNACONF_MODEL_API_KEY": "vllm-global-key-12345",
                # Runtime-specific OpenAI API key
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-evaluator-key-67890",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(minimal_settings)],
                root_path=minimal_settings.parent,
            )

            # The critical assertion: evaluator should use its own API key
            evaluator_config = config.get_ai_config("evaluator")
            assert evaluator_config.api_key == "openai-evaluator-key-67890", "CRITICAL BUG: Evaluator runtime is not using its own API key!"

    def test_global_api_key_used_when_no_runtime_override(self, minimal_settings):
        """Test that global API key is used when no runtime-specific override exists."""
        with patch.dict(
            os.environ,
            {
                "DYNACONF_MODEL_API_KEY": "vllm-global-key",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(minimal_settings)],
                root_path=minimal_settings.parent,
            )

            # Default runtime should use global API key
            default_config = config.get_ai_config("default")
            assert default_config.api_key == "vllm-global-key"

    def test_multiple_runtimes_independent_api_keys(self, minimal_settings):
        """Test that multiple runtimes can have independent API keys."""
        with patch.dict(
            os.environ,
            {
                # Global vLLM
                "DYNACONF_MODEL_API_KEY": "vllm-global-key",
                "DYNACONF_MODEL_PROVIDER": "vllm",
                # Evaluator OpenAI
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "openai-evaluator-key",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                # Search vLLM (uses global key)
                "DYNACONF_RUNTIMES__SEARCH__MODEL_PROVIDER": "vllm",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(minimal_settings)],
                root_path=minimal_settings.parent,
            )

            # Default uses global key
            default_config = config.get_ai_config("default")
            assert default_config.api_key == "vllm-global-key"
            assert default_config.provider == "vllm"

            # Evaluator uses its own key
            evaluator_config = config.get_ai_config("evaluator")
            assert evaluator_config.api_key == "openai-evaluator-key"
            assert evaluator_config.provider == "openai"

            # Search uses global key (no override)
            search_config = config.get_ai_config("search")
            assert search_config.api_key == "vllm-global-key"
            assert search_config.provider == "vllm"

            # Verify no mixing
            assert evaluator_config.api_key != default_config.api_key
            assert evaluator_config.api_key != search_config.api_key

    def test_realistic_deployment_with_openai_evaluator(self, minimal_settings):
        """Test realistic scenario: vLLM global + OpenAI evaluator override."""
        with patch.dict(
            os.environ,
            {
                # Global vLLM configuration
                "DYNACONF_MODEL_PROVIDER": "vllm",
                "DYNACONF_MODEL_API_KEY": "6FEDGzTQd8Oea8OO4onA",
                "DYNACONF_MODEL_BASE_URL": "https://avs-vllm.q14.net/v1",
                "DYNACONF_MODEL_NAME": "default",
                # Evaluator OpenAI override
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_PROVIDER": "openai",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_API_KEY": "sk-svcacct-evaluator",
                "DYNACONF_RUNTIMES__EVALUATOR__MODEL_NAME": "gpt-5-mini-2025-08-07",
            },
            clear=False,
        ):
            config = Config(
                settings_files=[str(minimal_settings)],
                root_path=minimal_settings.parent,
            )

            # Global vLLM
            default_config = config.get_ai_config("default")
            assert default_config.provider == "vllm"
            assert default_config.api_key == "6FEDGzTQd8Oea8OO4onA"

            # Evaluator OpenAI
            evaluator_config = config.get_ai_config("evaluator")
            assert evaluator_config.provider == "openai"
            assert evaluator_config.api_key == "sk-svcacct-evaluator"
            assert evaluator_config.model_name == "gpt-5-mini-2025-08-07"

            # CRITICAL: Verify no API key mixing
            assert evaluator_config.api_key != default_config.api_key, "BUG DETECTED: Evaluator is using vLLM API key instead of OpenAI!"
