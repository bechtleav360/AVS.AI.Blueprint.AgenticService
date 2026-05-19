"""Unit tests for Config initialisation and low-level accessors."""

from pathlib import Path


from blueprint.agents.config import Config


class TestConfigInit:
    def test_loads_app_name_from_settings(self, base_config: Config) -> None:
        assert base_config.get("app_name") == "test-app"

    def test_loads_app_port_from_settings(self, base_config: Config) -> None:
        assert base_config.get("app_port") == 8000

    def test_get_package_root_returns_configured_path(self, base_settings_file: Path) -> None:
        config = Config(
            settings_files=[str(base_settings_file)],
            root_path=str(base_settings_file.parent),
        )
        assert config.get_package_root() == base_settings_file.parent

    def test_get_returns_value_for_existing_key(self, base_config: Config) -> None:
        assert base_config.get("model_provider") == "vllm"

    def test_get_returns_none_for_missing_key(self, base_config: Config) -> None:
        assert base_config.get("nonexistent_key") is None

    def test_get_returns_default_for_missing_key(self, base_config: Config) -> None:
        assert base_config.get("nonexistent_key", "fallback") == "fallback"

    def test_dot_placeholder_config_loads_without_error(self, write_settings) -> None:
        """Config with a dot_placeholder setting initialises successfully."""
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
            dot_placeholder = "DOT"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert config.get("dot_placeholder") == "DOT"

    def test_settings_without_dot_placeholder_leaves_keys_intact(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
            my_key = "value"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert config.get("my_key") == "value"


class TestProcessDynabox:
    """Unit tests for the _process_dynabox helper (tested directly)."""

    def test_replaces_placeholder_in_keys(self, base_config: Config) -> None:
        result = base_config._process_dynabox({"someDOTnested": "value"}, "DOT", ".")
        assert "some.nested" in result
        assert "someDOTnested" not in result

    def test_normalises_keys_to_lowercase(self, base_config: Config) -> None:
        result = base_config._process_dynabox({"SomeKey": "v", "UPPER": "v"}, "DOT", ".")
        assert "somekey" in result
        assert "upper" in result
        assert "SomeKey" not in result
        assert "UPPER" not in result

    def test_parses_json_string_values_to_dict(self, base_config: Config) -> None:
        result = base_config._process_dynabox({"cfg": '{"a": 1, "b": 2}'}, "DOT", ".")
        assert result["cfg"] == {"a": 1, "b": 2}

    def test_parses_json_string_values_to_list(self, base_config: Config) -> None:
        result = base_config._process_dynabox({"items": "[1, 2, 3]"}, "DOT", ".")
        assert result["items"] == [1, 2, 3]

    def test_leaves_plain_strings_unchanged(self, base_config: Config) -> None:
        result = base_config._process_dynabox({"greeting": "hello world"}, "DOT", ".")
        assert result["greeting"] == "hello world"

    def test_converts_keyed_list_to_dict(self, base_config: Config) -> None:
        input_box = {
            "items": [
                {"key": "alpha", "value": 1},
                {"key": "beta", "value": 2},
            ]
        }
        result = base_config._process_dynabox(input_box, "DOT", ".")
        assert result["items"] == {"alpha": {"value": 1}, "beta": {"value": 2}}

    def test_leaves_non_keyed_lists_unchanged(self, base_config: Config) -> None:
        result = base_config._process_dynabox({"nums": [1, 2, 3]}, "DOT", ".")
        assert result["nums"] == [1, 2, 3]

    def test_leaves_mixed_lists_unchanged(self, base_config: Config) -> None:
        """Lists where not every item is a dict with a 'key' field are left as-is."""
        result = base_config._process_dynabox({"mixed": [{"key": "x"}, "plain"]}, "DOT", ".")
        assert result["mixed"] == [{"key": "x"}, "plain"]

    def test_recurses_into_nested_dicts(self, base_config: Config) -> None:
        input_box = {"outerDOTinner": {"nestedDOTkey": "val"}}
        result = base_config._process_dynabox(input_box, "DOT", ".")
        assert "outer.inner" in result
        assert result["outer.inner"]["nested.key"] == "val"

    def test_returns_non_dict_input_unchanged(self, base_config: Config) -> None:
        assert base_config._process_dynabox("just a string", "DOT", ".") == "just a string"
        assert base_config._process_dynabox(42, "DOT", ".") == 42
