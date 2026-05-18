"""Unit tests for Config.get_runtime_config."""

from pathlib import Path


from blueprint.agents.config import Config


class TestGetRuntimeConfig:
    def test_returns_dict(self, base_config: Config) -> None:
        assert isinstance(base_config.get_runtime_config("default"), dict)

    def test_global_model_provider_present_for_default_runtime(self, base_config: Config) -> None:
        result = base_config.get_runtime_config("default")
        assert result.get("model_provider") == "vllm"

    def test_global_api_key_present_for_default_runtime(self, base_config: Config) -> None:
        result = base_config.get_runtime_config("default")
        assert result.get("model_api_key") == "test-global-key"

    def test_runtime_specific_provider_overrides_global(self, api_key_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )
        result = config.get_runtime_config("evaluator")
        assert result["model_provider"] == "openai"

    def test_runtime_specific_base_url_overrides_global(self, api_key_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )
        result = config.get_runtime_config("search")
        assert result["model_base_url"] == "https://avs-embed.q14.net/v1"

    def test_unknown_runtime_returns_global_defaults_only(self, api_key_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )
        result = config.get_runtime_config("unknown_runtime_xyz")
        assert result["model_provider"] == "vllm"
        assert result["model_api_key"] == "vllm-global-key-12345"

    def test_result_keys_are_all_lowercase(self, api_key_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(api_key_settings_file)],
            root_path=str(api_key_settings_file.parent),
        )
        result = config.get_runtime_config("evaluator")
        for key in result:
            assert key == key.lower(), f"Key '{key}' is not lowercase"
