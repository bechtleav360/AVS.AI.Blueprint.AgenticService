"""Unit tests for the settable ``envvar_prefix`` and the mistakes it refuses to make silently."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from blueprint.agents.config import Config
from blueprint.agents.config.config import (
    DEFAULT_ENVVAR_PREFIX,
    DEPLOYMENT_IDENTITY_KEYS,
    ENVVAR_PREFIX_OVERRIDE,
    ConfigError,
)

from tests.unit.agents.config.conftest import WriteSettings

PREFIXES_UNDER_TEST = ("DYNACONF_", "MYAPP_", "OTHER_", "BLUEPRINT_ENVVAR")


@pytest.fixture(autouse=True)
def clean_environment() -> Iterator[None]:
    """Remove any ambient variable that could satisfy or defeat a prefix under test.

    The shell running the tests may export DYNACONF_* values of its own, and every assertion
    here is about which spelling Dynaconf reads, so the environment has to start empty of them.
    """
    saved = {key: value for key, value in os.environ.items() if key.startswith(PREFIXES_UNDER_TEST)}
    for key in saved:
        del os.environ[key]
    yield
    os.environ.update(saved)


@pytest.fixture
def settings_file(write_settings: WriteSettings) -> Path:
    """A minimal project with no declared prefix."""
    return write_settings("""
        [development]
        app_name = "root-app"
        app_port = 8000
        model_name = "from-file"
        """)


@pytest.fixture
def prefixed_settings_file(write_settings: WriteSettings) -> Path:
    """The same project, declaring MYAPP as its prefix -- at the top level, where it is read."""
    return write_settings("""
        envvar_prefix = "MYAPP"

        [development]
        app_name = "root-app"
        app_port = 8000
        model_name = "from-file"
        """)


def load(path: Path) -> Config:
    return Config(settings_files=[str(path)], root_path=str(path.parent))


class TestResolution:
    def test_the_default_is_dynaconf(self, settings_file: Path) -> None:
        """An existing project declares nothing and must keep the prefix it has always used."""
        assert load(settings_file).envvar_prefix == DEFAULT_ENVVAR_PREFIX

    def test_the_default_prefix_overrides_a_file_value(self, settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DYNACONF_MODEL_NAME", "from-dynaconf")
        assert load(settings_file).get("model_name") == "from-dynaconf"

    def test_a_top_level_key_declares_the_prefix(self, prefixed_settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYAPP_MODEL_NAME", "from-myapp")
        config = load(prefixed_settings_file)
        assert (config.envvar_prefix, config.get("model_name")) == ("MYAPP", "from-myapp")

    def test_the_environment_override_beats_the_file(self, prefixed_settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An operator has to be able to change the prefix without editing the image."""
        monkeypatch.setenv(ENVVAR_PREFIX_OVERRIDE, "OTHER")
        monkeypatch.setenv("OTHER_MODEL_NAME", "from-other")
        monkeypatch.setenv("MYAPP_MODEL_NAME", "from-myapp")
        config = load(prefixed_settings_file)
        assert (config.envvar_prefix, config.get("model_name")) == ("OTHER", "from-other")

    def test_dynaconf_still_resolves_alongside_a_custom_prefix(self, prefixed_settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dynaconf always loads DYNACONF_* and cannot be told not to, so declaring a prefix adds one."""
        monkeypatch.setenv("DYNACONF_MODEL_NAME", "from-dynaconf")
        assert load(prefixed_settings_file).get("model_name") == "from-dynaconf"

    def test_a_custom_prefix_wins_over_dynaconf_for_the_same_key(
        self, prefixed_settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The declared prefix is loaded second, so it is the one that decides."""
        monkeypatch.setenv("DYNACONF_MODEL_NAME", "from-dynaconf")
        monkeypatch.setenv("MYAPP_MODEL_NAME", "from-myapp")
        assert load(prefixed_settings_file).get("model_name") == "from-myapp"

    def test_the_environment_is_selected_through_the_resolved_prefix(
        self, prefixed_settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """app_environment decides which section loads, so it must honour the declared prefix too."""
        monkeypatch.setenv("MYAPP_APP_ENVIRONMENT", "production")
        assert load(prefixed_settings_file).get("app_environment") == "production"

    def test_a_namespace_view_reports_the_same_prefix(self, prefixed_settings_file: Path) -> None:
        """One process, one prefix: a view shares the loaded tree and cannot have its own."""
        config = load(prefixed_settings_file)
        assert config.for_namespace("orders").envvar_prefix == config.envvar_prefix


class TestDisabled:
    @pytest.mark.parametrize("spelling", ["false", "FALSE", "no", "0", ""])
    def test_a_falsy_spelling_disables_the_prefix(self, settings_file: Path, monkeypatch: pytest.MonkeyPatch, spelling: str) -> None:
        monkeypatch.setenv(ENVVAR_PREFIX_OVERRIDE, spelling)
        assert load(settings_file).envvar_prefix is False

    def test_toml_false_disables_the_prefix(self, write_settings: WriteSettings) -> None:
        path = write_settings("""
            envvar_prefix = false

            [development]
            app_name = "root-app"
            app_port = 8000
            """)
        assert load(path).envvar_prefix is False

    def test_an_unprefixed_variable_resolves(self, settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENVVAR_PREFIX_OVERRIDE, "false")
        monkeypatch.setenv("MODEL_NAME", "bare")
        assert load(settings_file).get("model_name") == "bare"

    @pytest.mark.parametrize("key", sorted(DEPLOYMENT_IDENTITY_KEYS))
    def test_deployment_identity_stays_unreadable(self, settings_file: Path, monkeypatch: pytest.MonkeyPatch, key: str) -> None:
        """The whole process environment is now in the tree -- C6 is what keeps identity out of reach."""
        monkeypatch.setenv(ENVVAR_PREFIX_OVERRIDE, "false")
        monkeypatch.setenv(key.upper(), "leaked")
        config = load(settings_file)
        with pytest.raises(ValueError, match="deployment identity"):
            config.get(key)


class TestRejections:
    def test_a_lowercase_prefix_is_rejected_not_upper_cased(self, settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dynaconf would upper-case it and read a spelling that was never exported."""
        monkeypatch.setenv(ENVVAR_PREFIX_OVERRIDE, "myapp")
        with pytest.raises(ConfigError, match="upper-cases the prefix"):
            load(settings_file)

    @pytest.mark.parametrize("candidate", ["MY-APP", "A,B", "1APP", "MY APP", "_APP"])
    def test_an_unusable_alphabet_is_rejected(self, settings_file: Path, monkeypatch: pytest.MonkeyPatch, candidate: str) -> None:
        monkeypatch.setenv(ENVVAR_PREFIX_OVERRIDE, candidate)
        with pytest.raises(ConfigError, match=r"\[A-Z\]\[A-Z0-9_\]\*"):
            load(settings_file)

    @pytest.mark.parametrize("candidate", ["BLUEPRINT", "POD"])
    def test_a_prefix_that_would_expose_deployment_identity_is_rejected(
        self, settings_file: Path, monkeypatch: pytest.MonkeyPatch, candidate: str
    ) -> None:
        """Stripping BLUEPRINT_ from BLUEPRINT_GROUP yields 'group', which the C6 blocklist does not name."""
        monkeypatch.setenv(ENVVAR_PREFIX_OVERRIDE, candidate)
        with pytest.raises(ConfigError, match="collides with deployment identity"):
            load(settings_file)

    def test_true_names_no_prefix_and_is_rejected(self, write_settings: WriteSettings) -> None:
        path = write_settings("""
            envvar_prefix = true

            [development]
            app_name = "root-app"
            app_port = 8000
            """)
        with pytest.raises(ConfigError, match="names no prefix"):
            load(path)

    def test_a_non_string_is_rejected(self, write_settings: WriteSettings) -> None:
        path = write_settings("""
            envvar_prefix = 42

            [development]
            app_name = "root-app"
            app_port = 8000
            """)
        with pytest.raises(ConfigError, match="must be a string or false"):
            load(path)

    def test_a_prefix_declared_inside_a_section_is_rejected(self, write_settings: WriteSettings) -> None:
        """The natural mistake: next to app_name under [default], where nothing can read it."""
        path = write_settings("""
            [development]
            app_name = "root-app"
            app_port = 8000
            envvar_prefix = "MYAPP"
            """)
        with pytest.raises(ConfigError, match="inside a section"):
            load(path)

    def test_the_rejection_names_the_section(self, write_settings: WriteSettings) -> None:
        path = write_settings("""
            [development]
            app_name = "root-app"
            app_port = 8000
            envvar_prefix = "MYAPP"
            """)
        with pytest.raises(ConfigError, match="development.envvar_prefix"):
            load(path)
