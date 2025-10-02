"""Object-oriented configuration management using Dynaconf."""

import logging
import os
from typing import Any, Dict, List

from dynaconf import Dynaconf, Validator

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
                Validator("app_name", must_exist=True),
                Validator("app_port", must_exist=True, is_type_of=int),
                Validator("app_environment", must_exist=True),
            ],
        )

        self.validate()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.settings.get(key, default)

    def get_ai_config(self) -> Dict[str, Any]:
        """Get AI-related configuration."""
        config = {
            "provider": self.get("ai_model_provider"),
            "model_name": self.get("ai_model_name"),
            "api_key": self.get("ai_model_api_key"),
            "base_url": self.get("ai_model_base_url"),
            "max_tokens": self.get("ai_model_max_tokens"),
            "temperature": self.get("ai_model_temperature"),
            "concurrency_limit": self.get("ai_concurrent_requests"),
            "usage_limits": {
                "request_limit": self.get("ai_usage_request_limit"),
                "input_tokens_limit": self.get("ai_usage_input_tokens_limit"),
                "output_tokens_limit": self.get("ai_usage_output_tokens_limit"),
                "total_tokens_limit": self.get("ai_usage_total_tokens_limit"),
            },
        }
        return config

    def get_observability_config(self) -> Dict[str, Any]:
        """Get observability-related configuration."""
        return {
            "otel_endpoint": self.get("otel_exporter_otlp_endpoint"),
            "log_level": self.get("log_level"),
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
        except Exception as exc:
            logger.error("Configuration validation failed: %s", exc, exc_info=True)
            self._validation_errors.append(str(exc))
            return False

    def has_validation_errors(self) -> bool:
        """Return True if configuration validation detected errors."""

        return bool(self._validation_errors)

    def get_validation_errors(self) -> List[str]:
        """Return collected configuration validation errors."""

        return list(self._validation_errors)
