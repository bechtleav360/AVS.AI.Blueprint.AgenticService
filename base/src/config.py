"""Object-oriented configuration management using Dynaconf."""

import os
from pathlib import Path
from typing import Any, Dict

from dynaconf import Dynaconf, Validator


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""


class Config:
    """A class to manage the application's configuration using dynaconf."""

    def __init__(self, settings_files=None, root_path=None):
        """Initialize the configuration manager."""
        if root_path is None:
            root_path = Path(__file__).parent.parent  # Default to 'base' dir

        if settings_files is None:
            settings_files = ["settings.toml", ".secrets.toml"]

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
                Validator("log_level", must_exist=True, default="INFO"),
                # FIXME: Add your custom configuration validators here.
            ],
        )
        self.validate()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.settings.get(key, default)

    def get_secret(self, key: str, default: Any = None) -> Any:
        """Get a secret value, prioritizing environment variables."""
        env_value = os.getenv(key.upper())
        if env_value is not None:
            return env_value
        return self.settings.get(key.lower(), default)

    def get_ai_config(self) -> Dict[str, Any]:
        """Get AI-related configuration."""
        return {
            "provider": self.get("ai_model_provider", "openai"),
            "model_name": self.get("ai_model_name", "gpt-4"),
            "api_key": self.get_secret("ai_api_key"),
            "base_url": self.get_secret("ai_model_base_url"),
            "max_tokens": self.get("ai_model_max_tokens", 1000),
            "temperature": self.get("ai_model_temperature", 0.1),
        }

    def get_observability_config(self) -> Dict[str, Any]:
        """Get observability-related configuration."""
        return {
            "otel_endpoint": self.get_secret("otel_exporter_otlp_endpoint"),
            "service_name": self.get("otel_service_name", self.get("app_name")),
            "log_level": self.get("log_level"),
        }

    def validate(self):
        """Validate the configuration."""
        try:
            self.settings.validators.validate()
            if not 1 <= self.get("app_port") <= 65535:
                raise ConfigError(f"Invalid app port: {self.get('app_port')}")
            # FIXME: Add your domain-specific validations here.
        except Exception as e:
            raise ConfigError(f"Configuration validation failed: {e}")
