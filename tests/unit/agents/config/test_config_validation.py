"""Unit tests for Config.validate and validation error tracking."""

import pytest

from blueprint.agents.config import Config, ConfigError


class TestConfigValidation:
    def test_valid_config_validate_returns_true(self, base_config: Config) -> None:
        assert base_config.validate() is True

    def test_no_validation_errors_for_valid_config(self, base_config: Config) -> None:
        assert base_config.has_validation_errors() is False

    def test_get_validation_errors_empty_for_valid_config(self, base_config: Config) -> None:
        assert base_config.get_validation_errors() == []

    def test_get_validation_errors_returns_copy(self, base_config: Config) -> None:
        """Mutating the returned list must not affect the internal state."""
        errors = base_config.get_validation_errors()
        errors.append("injected")
        assert base_config.get_validation_errors() == []

    def test_port_zero_raises_config_error(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 0
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
        """)
        with pytest.raises(ConfigError, match="Invalid app port"):
            Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))

    def test_port_above_max_raises_config_error(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 65536
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
        """)
        with pytest.raises(ConfigError, match="Invalid app port"):
            Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))

    def test_port_1_is_valid(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 1
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert not config.has_validation_errors()

    def test_port_65535_is_valid(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 65535
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert not config.has_validation_errors()

    def test_vllm_without_api_key_raises_config_error(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "vllm"
        """)
        with pytest.raises(ConfigError, match="Missing API key for vLLM provider"):
            Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))

    def test_non_vllm_without_api_key_passes_validation(self, write_settings) -> None:
        """Providers other than vllm do not require an API key."""
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert not config.has_validation_errors()

    def test_no_provider_passes_validation(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert not config.has_validation_errors()
