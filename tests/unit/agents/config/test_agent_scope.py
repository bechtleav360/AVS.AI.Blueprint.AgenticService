"""Unit tests for the ``agent_scope`` parameter on Config.

Cover:
- Backward compatibility (no agent_scope → behaves as before)
- Scoped lookup hits scope first
- Scoped lookup falls back to root
- get_ai_config resolves scoped runtime block
- get_ai_config falls back to root globals for unset keys
- Validators enforce scoped app_name / app_port
- Validators tolerate missing root keys when scoped
- Dotted nested keys resolve under scope
- Raw .settings access stays unscoped
"""

from pathlib import Path

import pytest

from blueprint.agents.config import Config
from blueprint.agents.config.config import ConfigError
from tests.unit.agents.config.conftest import WriteSettings

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCOPE_FIXTURE = FIXTURES_DIR / "settings_agent_scope.toml"


@pytest.fixture
def scoped_config_foo() -> Config:
    return Config(
        settings_files=[str(SCOPE_FIXTURE)],
        root_path=str(SCOPE_FIXTURE.parent),
        agent_scope="foo",
    )


@pytest.fixture
def scoped_config_bar() -> Config:
    return Config(
        settings_files=[str(SCOPE_FIXTURE)],
        root_path=str(SCOPE_FIXTURE.parent),
        agent_scope="bar",
    )


class TestBackwardCompatibility:
    """A Config built without agent_scope must behave exactly as before."""

    def test_unscoped_get_returns_root_value(self, base_config: Config) -> None:
        assert base_config.get("app_name") == "test-app"
        assert base_config.get("app_port") == 8000

    def test_unscoped_get_runtime_config_uses_legacy_block(self, write_settings: WriteSettings) -> None:
        settings_file = write_settings(
            """
            [development]
            app_name = "legacy"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
            model_base_url = "https://example.com/v1"

            [development.runtimes.my_agent]
            model_name = "legacy-model"
            """
        )
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        runtime_cfg = config.get_runtime_config("my_agent")
        assert runtime_cfg["model_name"] == "legacy-model"

    def test_agent_scope_attribute_default_is_none(self, base_config: Config) -> None:
        assert base_config._agent_scope is None


class TestScopedLookup:
    def test_scoped_value_wins_over_root(self, scoped_config_foo: Config) -> None:
        # foo overrides nats_url
        assert scoped_config_foo.get("nats_url") == "nats://foo-override:4222"

    def test_falls_back_to_root_when_scope_missing(self, scoped_config_bar: Config) -> None:
        # bar does not override nats_url; root value is returned
        assert scoped_config_bar.get("nats_url") == "nats://shared:4222"

    def test_scoped_app_name_resolves(self, scoped_config_foo: Config) -> None:
        assert scoped_config_foo.get("app_name") == "foo-app"

    def test_scoped_app_port_resolves(self, scoped_config_foo: Config) -> None:
        assert scoped_config_foo.get("app_port") == 8101


class TestGetAiConfigScoped:
    def test_resolves_scoped_runtime_block(self, scoped_config_foo: Config) -> None:
        ai = scoped_config_foo.get_ai_config("my_agent")
        assert ai.model_name == "foo-model"
        assert ai.max_tokens == 9999

    def test_falls_back_to_root_for_unset_keys(self, scoped_config_foo: Config) -> None:
        ai = scoped_config_foo.get_ai_config("my_agent")
        # base_url not set under scope → falls back to root
        assert ai.base_url == "https://shared.example.com/v1"
        # api_key not set under scope → falls back to root
        assert ai.api_key == "shared-key"
        # provider not set under scope → falls back to root
        assert ai.provider == "vllm"

    def test_resolves_scoped_model_settings(self, scoped_config_foo: Config) -> None:
        ai = scoped_config_foo.get_ai_config("my_agent")
        assert ai.model_settings.get("temperature_override") == 0.42


class TestValidators:
    def test_missing_scoped_app_name_raises(self, write_settings: WriteSettings) -> None:
        settings_file = write_settings(
            """
            [development]
            app_environment = "development"

            [development.foo]
            app_port = 8101
            # app_name intentionally missing
            """
        )
        with pytest.raises(ConfigError):
            Config(
                settings_files=[str(settings_file)],
                root_path=str(settings_file.parent),
                agent_scope="foo",
            )

    def test_missing_scoped_app_port_raises(self, write_settings: WriteSettings) -> None:
        settings_file = write_settings(
            """
            [development]
            app_environment = "development"

            [development.foo]
            app_name = "foo-app"
            # app_port intentionally missing
            """
        )
        with pytest.raises(ConfigError):
            Config(
                settings_files=[str(settings_file)],
                root_path=str(settings_file.parent),
                agent_scope="foo",
            )

    def test_root_keys_not_required_when_scoped(self, write_settings: WriteSettings) -> None:
        # No root app_name / app_port; only scoped versions exist.
        settings_file = write_settings(
            """
            [development]
            app_environment = "development"

            [development.foo]
            app_name = "foo-app"
            app_port = 8101
            """
        )
        # Must not raise.
        config = Config(
            settings_files=[str(settings_file)],
            root_path=str(settings_file.parent),
            agent_scope="foo",
        )
        assert config.get("app_name") == "foo-app"
        assert config.get("app_port") == 8101


class TestDottedKeys:
    def test_scoped_dotted_key_wins(self, scoped_config_foo: Config) -> None:
        assert scoped_config_foo.get("cache.cache_dir") == ".cache/foo"

    def test_dotted_key_falls_back_to_root(self, scoped_config_bar: Config) -> None:
        # bar does not set cache.cache_dir; root value is used
        assert scoped_config_bar.get("cache.cache_dir") == ".cache/shared"


class TestRawSettingsUnscoped:
    def test_raw_settings_returns_root_value(self, scoped_config_foo: Config) -> None:
        # Direct .settings access bypasses scoping.
        # Root has no app_name (it's only under foo and bar), so raw access returns None.
        assert scoped_config_foo.settings.get("app_name") is None

    def test_raw_settings_returns_root_for_shared_keys(self, scoped_config_foo: Config) -> None:
        # Root nats_url exists; raw access returns it regardless of scope override.
        assert scoped_config_foo.settings.get("nats_url") == "nats://shared:4222"
