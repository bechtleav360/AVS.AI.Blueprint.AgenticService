"""Object-oriented configuration management using Dynaconf."""
import json
import logging

from dynaconf import Dynaconf, Validator
from dynaconf.validator import ValidationError
from dynaconf.utils.boxing import DynaBox
from typing import Any

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""


class Config:
    """A class to manage the application's configuration using dynaconf."""

    def __init__(self, settings_files=None, root_path=None):
        """Initialize the configuration manager."""

        # Temporarily set logger to INFO, before configuring logging
        logger.setLevel(logging.INFO)
        logger.root.setLevel(logging.INFO)
        self._validation_errors: list[str] = []

        # First pass: load config to get app_environment
        temp_settings = Dynaconf(
            settings_files=settings_files,
            environments=False,
            load_dotenv=False,
            merge_enabled=True,
            root_path=root_path
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

        # Replace DOT placeholders
        dot_placeholder = self.settings.get("dot_placeholder", "")
        if dot_placeholder:
            # Process the entire settings object
            processed = self._process_dynabox(self.settings, dot_placeholder, ".")
            # Update settings with processed values
            for key, value in processed.items():
                self.settings[key] = value

        self.validate()

    def _process_dynabox(self, box, placeholder, replacement):
        """Recursively process a DynaBox to replace placeholders in keys and convert to lowercase.
        Also attempts to parse string values as JSON if they appear to be JSON objects/arrays.
        """

        def _try_parse_json(possible_json_value):
            """Try to parse a string value as JSON, return original if not valid JSON."""
            if not isinstance(possible_json_value, str):
                return possible_json_value
            try:
                parsed = json.loads(possible_json_value)
                # Only return parsed if it's a dict or list, otherwise keep original
                return parsed if isinstance(parsed, (dict, list)) else possible_json_value
            except (json.JSONDecodeError, TypeError):
                return possible_json_value

        def _convert_keyed_list_to_dict(items):
            """Convert a list of dicts with 'key' field to a dictionary.

            Args:
                items: List of dictionaries, where each dict has a 'key' field

            Returns:
                Dictionary with keys from the 'key' field and values as the remaining dict items
            """
            if not isinstance(items, list):
                return items

            # Only convert if all items are dicts with a 'key' field
            if not all(isinstance(item, dict) and 'key' in item for item in items):
                return items

            list_to_keys_result = {}
            for item in items:
                key = item.pop('key')
                list_to_keys_result[key] = item
            return list_to_keys_result

        if isinstance(box, dict) or hasattr(box, 'items'):
            result = {}
            for key, value in list(box.items()):
                # Process the key - replace placeholder and convert to lowercase
                new_key = key.replace(placeholder, replacement).lower()

                # Process the value
                if isinstance(value, str):
                    # Try to parse as JSON first
                    value = _try_parse_json(value)

                # Convert lists with 'key' fields to dictionaries
                if isinstance(value, list):
                    value = _convert_keyed_list_to_dict(value)

                if isinstance(value, (dict, DynaBox)) or hasattr(value, 'items'):
                    new_value = self._process_dynabox(value, placeholder, replacement)
                elif isinstance(value, list):
                    new_value = [
                        self._process_dynabox(item, placeholder, replacement)
                        if isinstance(item, (dict, DynaBox)) or hasattr(item, 'items')
                        else _try_parse_json(item) if isinstance(item, str) else item
                        for item in value
                    ]
                else:
                    new_value = value

                # Only update if key changed to avoid unnecessary updates
                if new_key != key and hasattr(box, 'pop'):
                    box.pop(key, None)  # Remove old key if it exists
                result[new_key] = new_value  # Always use the new (lowercase) key
            return result
        return box

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.
        """

        env_var = self.settings.get(key, default)
        # Convert DynaBox to dict
        if isinstance(env_var, DynaBox):
            return env_var.to_dict()
        return env_var

    def get_runtime_config(self, runtime_name: str = "default") -> dict[str, Any]:
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

    def get_ai_config(self, runtime_name: str = "default") -> dict[str, Any]:
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

    def get_prompt_config(self, runtime_name: str = "default") -> dict[str, Any]:
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

    def get_observability_config(self) -> dict[str, Any]:
        """Get observability-related configuration."""
        return {
            "otel_enabled": self.get("otel_enabled", False),
            "otel_endpoint": self.get("otel_endpoint"),
            "otel_service_name": self.get(
                "otel_service_name", self.get("app_name", "agent-service")
            ),
            "log_level": self.get("log_level", "INFO"),
        }

    def get_event_publishing_config(self) -> dict[str, Any]:
        """Get complete event publishing configuration.

        Returns:
            Dictionary with event publishing configuration:
            - default_pubsub_name: The default Dapr pubsub component name
            - topic_mapping: Dictionary mapping event types to topics or routing configs
        """

        topic_mapping = self.get("event_publishing.topic_mappingg", {})
        for event_type, topic_config in topic_mapping.items():
            if isinstance(topic_config, str):
                topic_mapping[event_type] = {"topic": topic_config, "routing_key": None}
            elif not isinstance(topic_config, dict):
                raise ValueError(
                    f"Invalid topic mapping for event type '{event_type}': {topic_config}"
                )

        return {
            "default_pubsub_name": self.get(
                "event_publishing.default_pubsub_name", "pubsub"
            ),
            "topic_mapping": topic_mapping,
        }

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

    def get_validation_errors(self) -> list[str]:
        """Return collected configuration validation errors."""

        return list(self._validation_errors)

if __name__ == '__main__':
    config = Config(settings_files=[
        "C:\\Users\\jan.weber\\Repos\\BIOS\\Agents_Blueprint\\custom\\settings.toml",
        "C:\\Users\\jan.weber\\Repos\\BIOS\\Agents_Blueprint\\custom\\secrets.toml"
    ])
    mapping_config = config.get_event_publishing_config()
    print(mapping_config)

    print(mapping_config["topic_mapping"]["invoice.validated"])
