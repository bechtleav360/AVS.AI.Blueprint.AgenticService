"""Unit tests for API key configuration resolution.

This test suite validates that the configuration system correctly loads
and resolves API keys for different runtimes.
"""

from pathlib import Path


from blueprint.agents.config import Config


class TestAPIKeyResolution:
    """Test suite for API key resolution with runtime-specific overrides."""

    def test_global_api_key_loaded_from_settings(self, api_key_settings_file: Path) -> None:
        """Test that global API key is loaded from settings file."""
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )

        assert config.get("model_api_key") == "vllm-global-key-12345"
        assert config.get("model_provider") == "vllm"

    def test_runtime_specific_settings_accessible(self, api_key_settings_file: Path) -> None:
        """Test that runtime-specific settings are accessible from settings."""
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )

        evaluator_settings = config.settings.get("runtimes.evaluator")
        assert evaluator_settings is not None
        assert evaluator_settings.get("model_provider") == "openai"
        assert evaluator_settings.get("model_api_key") == "openai-evaluator-key-67890"

    def test_search_runtime_settings_accessible(self, api_key_settings_file: Path) -> None:
        """Test that search runtime settings are accessible."""
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )

        search_settings = config.settings.get("runtimes.search")
        assert search_settings is not None
        assert search_settings.get("model_provider") == "vllm"
        assert search_settings.get("model_base_url") == "https://avs-embed.q14.net/v1"

    def test_multiple_runtimes_have_different_configurations(self, api_key_settings_file: Path) -> None:
        """Test that multiple runtimes can have different configurations."""
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )

        evaluator = config.settings.get("runtimes.evaluator")
        assert evaluator.get("model_provider") == "openai"
        assert evaluator.get("model_api_key") == "openai-evaluator-key-67890"

        search = config.settings.get("runtimes.search")
        assert search.get("model_provider") == "vllm"
        assert search.get("model_base_url") == "https://avs-embed.q14.net/v1"

        assert evaluator.get("model_api_key") != search.get("model_api_key", config.get("model_api_key"))

    def test_global_defaults_are_available(self, api_key_settings_file: Path) -> None:
        """Test that global defaults are available for all runtimes."""
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )

        assert config.get("model_provider") == "vllm"
        assert config.get("model_api_key") == "vllm-global-key-12345"
        assert config.get("model_base_url") == "https://avs-vllm.q14.net/v1"
        assert config.get("model_max_tokens") == 3000
        assert config.get("model_temperature") == 0.1
