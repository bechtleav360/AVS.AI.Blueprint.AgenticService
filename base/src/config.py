"""Object-oriented configuration management using Dynaconf."""

import logging
from typing import Any, Dict, List

from dynaconf import Dynaconf, Validator
from dynaconf.validator import ValidationError

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""


class Config:
    """A class to manage the application's configuration using dynaconf."""

    def __init__(self, settings_files=None, root_path=None):
        """Initialize the configuration manager."""

        self._validation_errors: List[str] = []

        # First pass: load config to get app_environment
        temp_settings = Dynaconf(
            settings_files=settings_files,
            environments=False,
            load_dotenv=False,
            merge_enabled=True,
            root_path=root_path,
        )
        app_env = temp_settings.get("app_environment", "development")
        logger.info("Loading configuration properties for environment: %s", app_env)

        # Second pass: load with the correct environment
        self.settings = Dynaconf(
            settings_files=settings_files,
            environments=True,
            current_env=app_env,
            load_dotenv=False,
            merge_enabled=True,
            root_path=root_path,
            validators=[
                Validator("app_name", must_exist=True, default="agent_blueprint"),
                Validator("app_port", must_exist=True, is_type_of=int, default=8000),
                Validator("app_environment", must_exist=True, default="development"),
            ],
        )

        self.validate()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.settings.get(key, default)

    def get_runtime_config(self, runtime_name: str = "default") -> Dict[str, Any]:
        """Get runtime-specific configuration merged with global defaults.

        Args:
            runtime_name: Name of the runtime to get config for.

        Returns:
            Merged configuration dictionary with runtime-specific overrides.
        """
        # Start with empty config
        config = {}

        # Add global defaults for common keys
        global_keys = [
            "ai_model_provider",
            "ai_model_base_url",
            "ai_model_api_key",
            "ai_model_max_tokens",
            "ai_model_temperature",
            "ai_concurrent_requests",
            "prompt_directory",
            "prompt_search_paths",
        ]

        for key in global_keys:
            value = self.get(key)
            if value is not None:
                config[key] = value

        # Override with runtime-specific config if it exists
        runtime_key = f"runtime.{runtime_name}"
        runtime_config = self.settings.get(runtime_key, {})
        if runtime_config:
            config.update(runtime_config)
            logger.debug(
                "Loaded runtime-specific config for '%s': %d settings",
                runtime_name,
                len(runtime_config),
            )
        else:
            logger.debug(
                "No runtime-specific config found for '%s', using global defaults",
                runtime_name,
            )

        return config

    def get_ai_config(self, runtime_name: str = "default") -> Dict[str, Any]:
        """Get AI-related configuration for a specific runtime.

        Args:
            runtime_name: Name of the runtime to get AI config for.

        Returns:
            AI configuration dictionary with runtime-specific overrides.
        """
        runtime_config = self.get_runtime_config(runtime_name)

        config = {
            "provider": runtime_config.get(
                "ai_model_provider", self.get("ai_model_provider")
            ),
            "model_name": runtime_config.get(
                "ai_model_name", self.get("ai_model_name")
            ),
            "api_key": runtime_config.get(
                "ai_model_api_key", self.get("ai_model_api_key")
            ),
            "base_url": runtime_config.get(
                "ai_model_base_url", self.get("ai_model_base_url")
            ),
            "max_tokens": runtime_config.get(
                "ai_model_max_tokens", self.get("ai_model_max_tokens")
            ),
            "temperature": runtime_config.get(
                "ai_model_temperature", self.get("ai_model_temperature")
            ),
            "concurrency_limit": runtime_config.get(
                "ai_concurrent_requests", self.get("ai_concurrent_requests")
            ),
            "usage_limits": {
                "request_limit": runtime_config.get(
                    "ai_usage_request_limit", self.get("ai_usage_request_limit")
                ),
                "input_tokens_limit": runtime_config.get(
                    "ai_usage_input_tokens_limit",
                    self.get("ai_usage_input_tokens_limit"),
                ),
                "output_tokens_limit": runtime_config.get(
                    "ai_usage_output_tokens_limit",
                    self.get("ai_usage_output_tokens_limit"),
                ),
                "total_tokens_limit": runtime_config.get(
                    "ai_usage_total_tokens_limit",
                    self.get("ai_usage_total_tokens_limit"),
                ),
            },
        }
        return config

    def get_prompt_config(self, runtime_name: str = "default") -> Dict[str, Any]:
        """Get prompt-related configuration for a specific runtime.

        Args:
            runtime_name: Name of the runtime to get prompt config for.

        Returns:
            Dictionary with prompt configuration:
            - custom_path: Optional custom path to prompt directory
            - search_paths: Optional list of additional search paths
            - system_prompt_name: Name of system prompt file (default: "system")
            - instruction_prompt_name: Name of instruction prompt file (default: "instruction")
        """
        runtime_config = self.get_runtime_config(runtime_name)

        return {
            "custom_path": runtime_config.get(
                "prompt_directory", self.get("prompt_directory")
            ),
            "search_paths": runtime_config.get(
                "prompt_search_paths", self.get("prompt_search_paths", [])
            ),
            "system_prompt_name": runtime_config.get(
                "system_prompt_name", self.get("system_prompt_name", "system")
            ),
            "instruction_prompt_name": runtime_config.get(
                "instruction_prompt_name",
                self.get("instruction_prompt_name", "instruction"),
            ),
        }

    def get_observability_config(self) -> Dict[str, Any]:
        """Get observability-related configuration."""
        return {
            "otel_endpoint": self.get("otel_exporter_otlp_endpoint"),
            "log_level": self.get("log_level"),
        }

    def get_event_publishing_config(self) -> Dict[str, Any]:
        """Get complete event publishing configuration.

        Returns:
            Dictionary with event publishing configuration:
            - default_pubsub_name: The default Dapr pubsub component name
            - topic_mapping: Dictionary mapping event types to topics
        """
        return {
            "default_pubsub_name": self.get(
                "event_publishing.default_pubsub_name", "pubsub"
            ),
            "topic_mapping": self.get("event_publishing.topic_mapping", {}),
        }

    def get_topic_for_event_type(self, event_type: str) -> str | None:
        """Get the topic name for a specific event type.

        Args:
            event_type: The CloudEvent type (e.g., "agent.output.invoice.processed")

        Returns:
            The topic name to publish to, or None if no mapping exists
        """
        topic_mapping = self.get("event_publishing.topic_mapping", {})
        return topic_mapping.get(event_type)

    def validate(self):
        """Validate the configuration."""
        self._validation_errors.clear()
        try:
            self.settings.validators.validate()
            if not 1 <= self.get("app_port") <= 65535:
                raise ConfigError(f"Invalid app port: {self.get('app_port')}")

            ai_config = self.get_ai_config()
            if ai_config.get("provider") == "vllm" and not ai_config.get("api_key"):
                raise ConfigError("Missing API key for vLLM provider")

            return True
        except ValidationError as exc:
            # Handle Dynaconf validation errors without stack trace
            error_msg = str(exc)
            logger.error("Configuration validation failed: %s", error_msg)
            self._validation_errors.append(error_msg)
            raise ConfigError(error_msg) from None
        except ConfigError as exc:
            # Re-raise ConfigError without stack trace
            logger.error("Configuration validation failed: %s", exc)
            self._validation_errors.append(str(exc))
            raise
        except Exception as exc:
            # Catch any other unexpected errors with stack trace for debugging
            logger.error("Unexpected configuration error: %s", exc, exc_info=True)
            self._validation_errors.append(str(exc))
            raise ConfigError(str(exc)) from exc

    def has_validation_errors(self) -> bool:
        """Return True if configuration validation detected errors."""

        return bool(self._validation_errors)

    def get_validation_errors(self) -> List[str]:
        """Return collected configuration validation errors."""

        return list(self._validation_errors)
