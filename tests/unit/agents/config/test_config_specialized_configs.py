"""Unit tests for Config specialised config getters.

Covers: get_prompt_config, get_observability_config,
        get_cache_config, get_event_publishing_config, get_nats_subscription_config,
        get_sessions_config.
"""

import pytest

from blueprint.agents.config import Config
from blueprint.agents.config.config import ConfigError
from blueprint.agents.models.config import (
    CacheConfig,
    EventPublishingConfig,
    ObservabilityConfig,
    PromptConfig,
    SessionsServiceConfig,
)


class TestGetObservabilityConfig:
    def test_returns_observability_config_instance(self, base_config: Config) -> None:
        assert isinstance(base_config.get_observability_config(), ObservabilityConfig)

    def test_otel_disabled_by_default(self, base_config: Config) -> None:
        assert base_config.get_observability_config().otel_enabled is False

    def test_log_level_read_from_settings(self, base_config: Config) -> None:
        assert base_config.get_observability_config().log_level == "INFO"

    def test_otel_endpoint_none_when_not_configured(self, base_config: Config) -> None:
        assert base_config.get_observability_config().otel_endpoint is None

    def test_custom_otel_settings_are_reflected(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
            otel_enabled = true
            otel_endpoint = "http://collector:4317"
            otel_service_name = "my-service"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        result = config.get_observability_config()
        assert result.otel_enabled is True
        assert result.otel_endpoint == "http://collector:4317"
        assert result.otel_service_name == "my-service"

    def test_service_name_falls_back_to_app_name(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "my-agent"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert config.get_observability_config().otel_service_name == "my-agent"


class TestGetCacheConfig:
    def test_returns_cache_config_instance(self, base_config: Config) -> None:
        assert isinstance(base_config.get_cache_config(), CacheConfig)

    def test_default_cache_dir(self, base_config: Config) -> None:
        assert base_config.get_cache_config().cache_dir == ".cache/blueprint"

    def test_default_size_limit(self, base_config: Config) -> None:
        assert base_config.get_cache_config().size_limit == 1_000_000_000

    def test_default_eviction_policy(self, base_config: Config) -> None:
        assert base_config.get_cache_config().eviction_policy == "least-recently-used"

    def test_default_ttl(self, base_config: Config) -> None:
        assert base_config.get_cache_config().default_ttl == 3600

    def test_custom_cache_section_overrides_defaults(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"

            [development.cache]
            cache_dir = "/tmp/my-cache"
            size_limit = 500000000
            eviction_policy = "least-frequently-used"
            default_ttl = 1800
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        result = config.get_cache_config()
        assert result.cache_dir == "/tmp/my-cache"
        assert result.size_limit == 500_000_000
        assert result.eviction_policy == "least-frequently-used"
        assert result.default_ttl == 1800


class TestGetEventPublishingConfig:
    def test_returns_event_publishing_config_instance(self, base_config: Config) -> None:
        assert isinstance(base_config.get_event_publishing_config(), EventPublishingConfig)

    def test_default_pubsub_name(self, base_config: Config) -> None:
        assert base_config.get_event_publishing_config().default_pubsub_name == "pubsub"

    def test_empty_topic_mapping_by_default(self, base_config: Config) -> None:
        assert base_config.get_event_publishing_config().topic_mapping == {}

    def test_custom_pubsub_name_from_settings(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"

            [development.event_publishing]
            default_pubsub_name = "my-pubsub"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert config.get_event_publishing_config().default_pubsub_name == "my-pubsub"


class TestGetPromptConfig:
    def test_returns_prompt_config_instance(self, base_config: Config) -> None:
        assert isinstance(base_config.get_prompt_config(), PromptConfig)

    def test_default_system_prompt_name(self, base_config: Config) -> None:
        assert base_config.get_prompt_config().system_prompt_name == "system"

    def test_default_instruction_prompt_name(self, base_config: Config) -> None:
        assert base_config.get_prompt_config().instruction_prompt_name == "instruction"

    def test_custom_path_none_when_not_configured(self, base_config: Config) -> None:
        assert base_config.get_prompt_config().custom_path is None

    def test_custom_prompt_directory_is_reflected(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
            prompt_directory = "/custom/prompts"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert config.get_prompt_config().custom_path == "/custom/prompts"

    def test_custom_prompt_names_from_settings(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
            system_prompt_name = "sys_v2"
            instruction_prompt_name = "instr_v2"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        result = config.get_prompt_config()
        assert result.system_prompt_name == "sys_v2"
        assert result.instruction_prompt_name == "instr_v2"


class TestGetNatsSubscriptionConfig:
    def test_returns_empty_list_when_key_absent(self, base_config: Config) -> None:
        assert base_config.get_nats_subscription_config() == []

    def test_returns_configured_topics(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"
            nats_subscriptions = ["governance.>", "orders.created"]
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        assert config.get_nats_subscription_config() == ["governance.>", "orders.created"]

    def test_non_list_value_returns_empty_list(self, base_config: Config, monkeypatch) -> None:
        monkeypatch.setattr(
            base_config,
            "get",
            lambda key, default=None: "single.topic" if key == "nats_subscriptions" else default,
        )
        assert base_config.get_nats_subscription_config() == []

    def test_non_list_value_logs_warning(self, base_config: Config, monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
        monkeypatch.setattr(
            base_config,
            "get",
            lambda key, default=None: "single.topic" if key == "nats_subscriptions" else default,
        )
        with caplog.at_level("WARNING"):
            base_config.get_nats_subscription_config()
        assert "nats_subscriptions must be a list" in caplog.text

    def test_falsy_entries_are_filtered_out(self, base_config: Config, monkeypatch) -> None:
        monkeypatch.setattr(
            base_config,
            "get",
            lambda key, default=None: ["valid.topic", "", None] if key == "nats_subscriptions" else default,
        )
        assert base_config.get_nats_subscription_config() == ["valid.topic"]


class TestGetSessionsConfig:
    def test_returns_none_when_block_absent(self, base_config: Config) -> None:
        # The base fixture has no [sessions_service] block — REST-only agents are
        # a normal state, so absence must degrade to None, not raise.
        assert base_config.get_sessions_config() is None

    def test_returns_validated_config_when_present(self, write_settings) -> None:
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"

            [development.sessions_service]
            base_url = "http://sessions.local:8000"
            api_key = "test-api-key"
            agent_id = "classifier-1"
            capabilities = ["classify.document"]
            max_concurrent_jobs = 4
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        result = config.get_sessions_config()
        assert isinstance(result, SessionsServiceConfig)
        assert result.base_url == "http://sessions.local:8000"
        assert result.api_key == "test-api-key"
        assert result.agent_id == "classifier-1"
        assert result.capabilities == ["classify.document"]
        assert result.max_concurrent_jobs == 4

    def test_optional_fields_fall_back_to_model_defaults(self, write_settings) -> None:
        # Only the required fields are set; everything else must come from the
        # framework's SessionsServiceConfig defaults, not a re-declared contract.
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"

            [development.sessions_service]
            base_url = "http://sessions.local:8000"
            api_key = "test-api-key"
            agent_id = "classifier-1"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        result = config.get_sessions_config()
        assert result is not None
        assert result.capabilities == []
        assert result.session_key_env_var == "SESSION_KEY"
        assert result.session_key_cache_ttl_seconds == 3600
        assert result.max_concurrent_jobs == 10
        assert result.health_check_enabled is True

    def test_partial_block_missing_required_field_raises_config_error(self, write_settings) -> None:
        # Block present but missing the required agent_id — a misconfiguration,
        # so it fails fast as a ConfigError rather than silently returning None.
        settings_file = write_settings("""
            [development]
            app_name = "test"
            app_port = 8000
            app_environment = "development"
            model_provider = "openai"
            model_api_key = "key"

            [development.sessions_service]
            base_url = "http://sessions.local:8000"
            api_key = "test-api-key"
        """)
        config = Config(settings_files=[str(settings_file)], root_path=str(settings_file.parent))
        with pytest.raises(ConfigError, match="sessions_service"):
            config.get_sessions_config()

    def test_empty_block_raises_config_error_not_none(self, base_config: Config, monkeypatch) -> None:
        # A present-but-empty table is the limiting case of "missing required
        # fields" — it must fail fast, not degrade to None like an absent key.
        monkeypatch.setattr(
            base_config,
            "get",
            lambda key, default=None: {} if key == "sessions_service" else default,
        )
        with pytest.raises(ConfigError, match="sessions_service"):
            base_config.get_sessions_config()

    def test_non_table_value_raises_config_error(self, base_config: Config, monkeypatch) -> None:
        # A non-mapping value (e.g. an [[sessions_service]] array-of-tables typo
        # surfacing as a list) must raise ConfigError, not leak a bare TypeError
        # from the model validation — callers catch ConfigError to degrade.
        monkeypatch.setattr(
            base_config,
            "get",
            lambda key, default=None: [{"base_url": "x"}] if key == "sessions_service" else default,
        )
        with pytest.raises(ConfigError, match="expected a table"):
            base_config.get_sessions_config()

    def test_absent_key_still_returns_none(self, base_config: Config, monkeypatch) -> None:
        # Only a genuinely absent key (get -> None) degrades to None.
        monkeypatch.setattr(
            base_config,
            "get",
            lambda key, default=None: None if key == "sessions_service" else default,
        )
        assert base_config.get_sessions_config() is None
