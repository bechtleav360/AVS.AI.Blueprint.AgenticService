"""Object-oriented configuration management using Dynaconf."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from dynaconf import Dynaconf, Validator


class ConfigError(Exception):
    """Custom exception for configuration-related errors."""
    pass


class Config:
    """A class to manage the application's configuration using Dynaconf."""

    def __init__(self):
        """Initialize the configuration manager."""
        project_root = Path(__file__).parent.parent
        self.settings = Dynaconf(
            settings_files=["settings.toml", ".secrets.toml"],
            environments=True,
            env_switcher="ENV_FOR_DYNACONF",
            load_dotenv=True,
            dotenv_path=project_root / ".env",
            merge_enabled=True,
            root_path=project_root,
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

