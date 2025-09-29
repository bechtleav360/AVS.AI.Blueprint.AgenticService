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
        self.settings = Dynaconf(
            settings_files=settings_files,
            environments=True,
            env_switcher="ENV_FOR_DYNACONF",
            load_dotenv=False,
            dotenv_path=root_path / ".env",
            merge_enabled=True,
            root_path=root_path,
            validators=[
                Validator("app_name", must_exist=True, default="agent-service"),
                Validator("app_port", must_exist=True, default=8000, is_type_of=int),
                Validator("log_level", default="INFO"),
                Validator("ai_model_provider", default="vllm"),
            ],
        )

        self.validate()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.settings.get(key, default)

    def get_secret(self, key: str, default: Any = None) -> Any:
        """Get a secret value, prioritizing environment variables."""
        env_key = key.upper()
        env_value = os.getenv(env_key)
        if env_value is not None:
            return env_value

        # Dynaconf is generally case-insensitive, but be explicit to be safe
        for candidate in (key, key.lower(), key.upper()):
            value = self.settings.get(candidate, None)
            if value is not None:
                return value
        return default

    def get_ai_config(self) -> Dict[str, Any]:
        """Get AI-related configuration."""
        return {
            "provider": self.get("ai_model_provider", "openai"),
            "model_name": self.get("ai_model_name", "gpt-4"),
            "api_key": self.get_secret("ai_model_api_key"),
            "base_url": self.get_secret("ai_model_base_url"),
            "max_tokens": self.get("ai_model_max_tokens", 1000),
            "temperature": self.get("ai_model_temperature", 0.1),
        }

    def get_observability_config(self) -> Dict[str, Any]:
        """Get observability-related configuration."""
        return {
            "otel_endpoint": self.get_secret("otel_exporter_otlp_endpoint"),
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
