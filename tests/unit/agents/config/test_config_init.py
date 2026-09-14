"""Unit tests for Config initialisation and low-level accessors."""

from pathlib import Path

import pytest
from unittest.mock import MagicMock


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


class TestLoggingIsTheApplicationsDecision:
    """Config loads configuration; it does not touch the root logger (see configure_logging)."""

    def test_construction_does_not_configure_logging(self, base_settings_file: Path, mock_logging_configure: MagicMock) -> None:
        Config(settings_files=[str(base_settings_file)], root_path=str(base_settings_file.parent))
        mock_logging_configure.return_value.configure.assert_not_called()

    def test_configure_logging_configures_on_request(self, base_config: Config, mock_logging_configure: MagicMock) -> None:
        base_config.configure_logging()
        mock_logging_configure.return_value.configure.assert_called_once()

    def test_configure_logging_passes_the_resolved_settings(self, base_config: Config, mock_logging_configure: MagicMock) -> None:
        base_config.configure_logging()
        assert mock_logging_configure.return_value.configure.call_args.kwargs["log_level"] == base_config.settings.get("log_level", "INFO")

    def test_two_configs_configure_nothing_between_them(self, base_settings_file: Path, mock_logging_configure: MagicMock) -> None:
        """One Config per namespace is the point of this move: N constructions, zero reconfigurations."""
        for _ in range(3):
            Config(settings_files=[str(base_settings_file)], root_path=str(base_settings_file.parent))
        mock_logging_configure.return_value.configure.assert_not_called()


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


class TestTheResolvedEnvironmentIsTheOneLoaded:
    """**The environment named in the configuration is the section that takes effect** (#89).

    *Failure it prevents:* the quietest kind there is. ``Config`` resolved ``app_environment``
    correctly, logged the name it had resolved, and then loaded a different environment -- the
    value went to Dynaconf as ``current_env``, which is a *derived* property reporting which
    environment is active rather than the parameter that selects one. The selector is ``env``.
    So a deployment could read ``Loading configuration properties for environment: production``
    in its own logs while every value came from the default section, and nothing disagreed.

    Each test asserts on a **marker that differs between the two sections**, never on the
    reported environment name: the name was always right, and that is precisely what kept the
    defect invisible for so long.

    ``app_environment`` is consumed by the first pass, which loads with ``environments=False``
    and therefore sees **top-level keys only** -- the same shape ``envvar_prefix`` requires, for
    the same reason. A declaration inside a section is invisible to it; the last test pins that
    so nobody reads this class as promising otherwise.
    """

    def _written(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "settings.toml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_non_default_environments_section_is_the_one_that_applies(self, tmp_path: Path) -> None:
        path = self._written(
            tmp_path,
            """
app_environment = "production"

[default]
app_name = "from-default"
app_port = 8000

[production]
app_name = "from-production"
app_port = 9999
""",
        )
        config = Config(settings_files=[str(path)], root_path=str(tmp_path))

        assert config.get("app_name") == "from-production"
        assert config.get("app_port") == 9999

    def test_the_default_environment_still_loads_its_own_section(self, tmp_path: Path) -> None:
        path = self._written(
            tmp_path,
            """
app_environment = "development"

[default]
app_name = "from-default"
app_port = 8000

[production]
app_name = "from-production"
app_port = 9999
""",
        )
        config = Config(settings_files=[str(path)], root_path=str(tmp_path))

        assert config.get("app_name") == "from-default"
        assert config.get("app_port") == 8000

    def test_keys_only_the_default_section_declares_are_still_inherited(self, tmp_path: Path) -> None:
        """Selecting an environment layers it over ``[default]``; it does not replace it."""
        path = self._written(
            tmp_path,
            """
app_environment = "production"

[default]
app_name = "from-default"
app_port = 8000
shared_key = "only-in-default"

[production]
app_name = "from-production"
""",
        )
        config = Config(settings_files=[str(path)], root_path=str(tmp_path))

        assert config.get("app_name") == "from-production"
        assert config.get("shared_key") == "only-in-default"

    def test_the_environment_variable_selects_too(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The realistic deployment route: one image, the section chosen per environment."""
        path = self._written(
            tmp_path,
            """
[default]
app_name = "from-default"
app_port = 8000

[production]
app_name = "from-production"
app_port = 9999
""",
        )
        monkeypatch.setenv("DYNACONF_APP_ENVIRONMENT", "production")
        config = Config(settings_files=[str(path)], root_path=str(tmp_path))

        assert config.get("app_name") == "from-production"

    def test_a_sectioned_declaration_is_not_seen_by_the_first_pass(self, tmp_path: Path) -> None:
        """Documents the trap rather than promising it works: the first pass reads top level only."""
        path = self._written(
            tmp_path,
            """
[default]
app_environment = "production"
app_name = "from-default"
app_port = 8000

[production]
app_name = "from-production"
""",
        )
        config = Config(settings_files=[str(path)], root_path=str(tmp_path))

        assert config.get("app_name") == "from-default"
