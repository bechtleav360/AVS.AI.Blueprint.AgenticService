"""Unit tests for Config specialised config getters.

Covers: get_prompt_config, get_observability_config,
        get_cache_config, get_event_publishing_config, get_nats_subscription_config.
"""

import pytest

from blueprint.agents.config import Config
from blueprint.agents.models.config import (
    CacheConfig,
    EventPublishingConfig,
    ObservabilityConfig,
    PromptConfig,
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
