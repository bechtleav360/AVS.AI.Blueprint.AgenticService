"""Object-oriented configuration management using Dynaconf."""

import json
import logging
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf, Validator
from dynaconf.utils.boxing import DynaBox
from dynaconf.validator import ValidationError

from ..models.config import AIConfig, CacheConfig, EventPublishingConfig, ObservabilityConfig, PromptConfig, UsageLimits
from .custom_logging import LoggingManager

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""


class Config:
    """A class to manage the application's configuration using dynaconf."""

    def __init__(self, settings_files=None, root_path=None):
        """Initialize the configuration manager."""

        self._validation_errors: list[str] = []
        self._root_path = Path(root_path) if root_path else Path.cwd()

        # First pass: load config to get app_environment
        temp_settings = Dynaconf(
            settings_files=settings_files, environments=False, load_dotenv=False, merge_enabled=True, root_path=root_path
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

        # Initialize logging after config is fully loaded
        self._initialize_logging()

    def get_package_root(self) -> Path:
        """Return the root path where configuration files are located."""

        return self._root_path

    def _initialize_logging(self) -> None:
        """Initialize logging based on configuration.

        Called automatically at the end of Config initialization.
        Sets up logging with the configured log level and format from settings.
        """
        log_level = self.settings.get("log_level", "INFO")
        log_format = self.settings.get("log_format", "text")
        suppress_noisy = self.settings.get("suppress_noisy_loggers", True)

        manager = LoggingManager()
        manager.configure(log_level=log_level, log_format=log_format, suppress_noisy_loggers=suppress_noisy)

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
            if not all(isinstance(item, dict) and "key" in item for item in items):
                return items

            list_to_keys_result = {}
            for item in items:
                key = item.pop("key")
                list_to_keys_result[key] = item
            return list_to_keys_result

        if isinstance(box, dict) or hasattr(box, "items"):
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

                if isinstance(value, (dict, DynaBox)) or hasattr(value, "items"):
                    new_value = self._process_dynabox(value, placeholder, replacement)
                elif isinstance(value, list):
                    new_value = [
                        (
                            self._process_dynabox(item, placeholder, replacement)
                            if isinstance(item, (dict, DynaBox)) or hasattr(item, "items")
                            else _try_parse_json(item) if isinstance(item, str) else item
                        )
                        for item in value
                    ]
                else:
                    new_value = value

                # Only update if key changed to avoid unnecessary updates
                if new_key != key and hasattr(box, "pop"):
                    box.pop(key, None)  # Remove old key if it exists
                result[new_key] = new_value  # Always use the new (lowercase) key
            return result
        return box

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""

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

        # Add global defaults for common keys (using new model_* pattern)
        global_keys = [
            "model_provider",
            "model_base_url",
            "model_api_key",
            "model_max_tokens",
            "model_temperature",
            "concurrent_requests",
            "prompt_directory",
            "prompt_search_paths",
        ]

        for key in global_keys:
            value = self.get(key)
            if value is not None:
                config[key] = value

        # Override with runtime-specific config if it exists
        runtime_config = None

        # Try to find runtime-specific config
        runtime_config = self.settings.get(f"runtimes.{runtime_name}")
        if not runtime_config:
            runtime_config = self.settings.get(f"runtimes.{runtime_name.upper()}")
        if not runtime_config:
            runtimes = self.settings.get("runtimes")
            if runtimes and hasattr(runtimes, "get"):
                runtime_config = runtimes.get(runtime_name) or runtimes.get(runtime_name.upper())
        if not runtime_config:
            runtime_config = self.settings.get(f"runtime.{runtime_name}")
        if not runtime_config:
            runtime_config = self.settings.get(f"runtime.{runtime_name.upper()}")

        # Process runtime-specific config if found
        if runtime_config:
            # Convert uppercase keys to lowercase for consistency
            normalized_config = {}
            for key, value in runtime_config.items():
                normalized_key = key.lower() if isinstance(key, str) else key
                normalized_config[normalized_key] = value

            config.update(normalized_config)
            logger.debug(
                "Loaded runtime-specific config for '%s': %d settings",
                runtime_name,
                len(normalized_config),
            )
        else:
            logger.debug(
                "No runtime-specific config found for '%s', using global defaults",
                runtime_name,
            )
        return config

    def get_ai_config(self, runtime_name: str = "default") -> AIConfig:
        """Get AI-related configuration for a specific runtime.

        Supports both old (ai_model_*) and new (model_*) configuration patterns.
        The new pattern is preferred for runtime-specific configs.

        Args:
            runtime_name: Name of the runtime to get AI config for.

        Returns:
            AIConfig model with runtime-specific overrides.
        """
        # Get runtime-specific settings directly from settings
        runtime_settings = self.settings.get(f"runtimes.{runtime_name}")
        if not runtime_settings:
            runtime_settings = {}

        # Helper to get config value with fallback from runtime-specific to global
        def get_with_fallback(key: str) -> Any:
            """Get config value, trying runtime-specific first, then global.

            Priority order:
            1. Runtime-specific (e.g., model_api_key in runtimes.evaluator)
            2. Global (e.g., model_api_key at root level)
            """
            # Try runtime-specific first
            value = runtime_settings.get(key)
            if value is not None:
                return value
            # Fall back to global
            return self.get(key)

        provider = get_with_fallback("model_provider")
        model_name = get_with_fallback("model_name")
        api_key = get_with_fallback("model_api_key")
        base_url = get_with_fallback("model_base_url")

        # Log configuration resolution for debugging
        logger.debug(
            "AI config for runtime '%s': provider=%s, model=%s, has_api_key=%s, base_url=%s",
            runtime_name,
            provider,
            model_name,
            "yes" if api_key else "no",
            base_url,
        )

        return AIConfig(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            max_tokens=get_with_fallback("model_max_tokens"),
            temperature=get_with_fallback("model_temperature"),
            concurrency_limit=get_with_fallback("concurrent_requests"),
            usage_limits=UsageLimits(
                request_limit=get_with_fallback("usage_request_limit"),
                input_tokens_limit=get_with_fallback("usage_input_tokens_limit"),
                output_tokens_limit=get_with_fallback("usage_output_tokens_limit"),
                total_tokens_limit=get_with_fallback("usage_total_tokens_limit"),
            ),
        )

    def get_prompt_config(self, runtime_name: str = None) -> PromptConfig:
        """Get prompt-related configuration for a specific runtime.

        Args:
            runtime_name: Name of the runtime to get prompt config for.

        Returns:
            PromptConfig model with prompt configuration.
        """
        runtime_config = self.get_runtime_config(runtime_name)

        return PromptConfig(
            custom_path=runtime_config.get("prompt_directory", self.get("prompt_directory")),
            search_paths=runtime_config.get("prompt_search_paths", self.get("prompt_search_paths", [])),
            system_prompt_name=runtime_config.get("system_prompt_name", self.get("system_prompt_name", "system")),
            instruction_prompt_name=runtime_config.get(
                "instruction_prompt_name",
                self.get("instruction_prompt_name", "instruction"),
            ),
        )

    def get_observability_config(self) -> ObservabilityConfig:
        """Get observability-related configuration."""
        return ObservabilityConfig(
            otel_enabled=self.get("otel_enabled", False),
            otel_endpoint=self.get("otel_endpoint"),
            otel_service_name=self.get("otel_service_name", self.get("app_name", "agent-service")),
            log_level=self.get("log_level", "INFO"),
        )

    def get_event_publishing_config(self) -> EventPublishingConfig:
        """Get complete event publishing configuration.

        Returns:
            EventPublishingConfig model with event publishing configuration.
        """

        return EventPublishingConfig(
            default_pubsub_name=self.get("event_publishing.default_pubsub_name", "pubsub"),
            topic_mapping=self.get("event_publishing.topic_mapping", {}),
        )

    def get_cache_config(self) -> CacheConfig:
        """Get cache-related configuration.

        Returns:
            CacheConfig model with cache configuration.
        """

        return CacheConfig(
            cache_dir=self.get("cache.cache_dir", ".cache/blueprint"),
            size_limit=self.get("cache.size_limit", 1_000_000_000),
            eviction_policy=self.get("cache.eviction_policy", "least-recently-used"),
            default_ttl=self.get("cache.default_ttl", 3600),
        )

    def validate(self):
        """Validate the configuration."""
        self._validation_errors.clear()
        try:
            self.settings.validators.validate()
            if not 1 <= self.get("app_port") <= 65535:
                raise ConfigError(f"Invalid app port: {self.get('app_port')}")

            ai_config = self.get_ai_config()
            if ai_config.provider == "vllm" and not ai_config.api_key:
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
