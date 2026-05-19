"""Unit tests for Config.get_ai_config."""

from pathlib import Path


from blueprint.agents.config import Config
from blueprint.agents.models.config import AIConfig


class TestGetAIConfig:
    def test_returns_ai_config_instance(self, base_config: Config) -> None:
        assert isinstance(base_config.get_ai_config(), AIConfig)

    def test_global_provider_populated(self, base_config: Config) -> None:
        assert base_config.get_ai_config().provider == "vllm"

    def test_global_api_key_populated(self, base_config: Config) -> None:
        assert base_config.get_ai_config().api_key == "test-global-key"

    def test_global_base_url_populated(self, base_config: Config) -> None:
        assert base_config.get_ai_config().base_url == "https://test.example.com/v1"

    def test_global_max_tokens_populated(self, base_config: Config) -> None:
        assert base_config.get_ai_config().max_tokens == 2000

    def test_global_temperature_populated(self, base_config: Config) -> None:
        assert base_config.get_ai_config().temperature == 0.7

    def test_usage_limits_default_to_none_when_not_set(self, base_config: Config) -> None:
        limits = base_config.get_ai_config().usage_limits
        assert limits.request_limit is None
        assert limits.input_tokens_limit is None
        assert limits.output_tokens_limit is None
        assert limits.total_tokens_limit is None

    def test_runtime_provider_overrides_global(self, api_key_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )
        assert config.get_ai_config("evaluator").provider == "openai"

    def test_runtime_api_key_overrides_global(self, api_key_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )
        assert config.get_ai_config("evaluator").api_key == "openai-evaluator-key-67890"

    def test_runtime_model_name_overrides_global(self, api_key_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )
        assert config.get_ai_config("evaluator").model_name == "gpt-4"

    def test_unknown_runtime_falls_back_to_global_provider(self, api_key_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )
        result = config.get_ai_config("nonexistent_runtime")
        assert result.provider == "vllm"
        assert result.api_key == "vllm-global-key-12345"

    def test_usage_limits_populated_when_configured(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
            usage_request_limit = 100
            usage_input_tokens_limit = 50000
            usage_output_tokens_limit = 10000
            usage_total_tokens_limit = 60000
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        limits = config.get_ai_config().usage_limits
        assert limits.request_limit == 100
        assert limits.input_tokens_limit == 50000
        assert limits.output_tokens_limit == 10000
        assert limits.total_tokens_limit == 60000
