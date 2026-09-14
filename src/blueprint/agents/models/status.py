"""Status-related data models for actuator endpoints."""

from typing import Any

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class ServiceInfo(BaseModel):
    """Service information including dependencies."""

    name: str = Field(
        ...,
        description="Application name.",
        examples=["agent-service"],
    )
    version: str = Field(
        ...,
        description="Application version.",
        examples=["1.0.0"],
    )
    dependencies: dict[str, str] = Field(
        ...,
        description="Installed dependencies and their versions.",
        examples=[{"fastapi": "0.109.0", "pydantic": "2.6.0"}],
    )


class EnvironmentStatus(BaseModel):
    """Environment configuration status."""

    environment: str = Field(
        ...,
        description="Current environment name.",
        examples=["development", "production"],
    )
    envvar_prefix: str | None = Field(
        default=None,
        description=(
            "Prefix an environment variable must carry to override a setting. Null means the "
            "prefix is disabled and the whole process environment is read unprefixed."
        ),
        examples=["DYNACONF", "ORDERS"],
    )
    settings: dict[str, Any] = Field(
        ...,
        description="Sanitized configuration the root namespace resolves.",
    )
    namespaces: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Sanitized configuration each co-hosted agent resolves, flattened as that agent "
            "reads it -- inherited root keys included. Empty for a single-agent service."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "environment": "development",
                "envvar_prefix": "DYNACONF",
                "settings": {
                    "app_name": "agent-service",
                    "api_key": "***",
                },
                "namespaces": {
                    "orders": {
                        "app_name": "orders",
                        "model_name": "gpt-4",
                        "api_key": "***",
                    }
                },
            }
        }
    )


class VLLMInfo(BaseModel):
    """vLLM provider information."""

    version: str = Field(
        ...,
        description="vLLM package version.",
        examples=["0.6.0"],
    )
    models: list[str] | None = Field(
        default=None,
        description="Available models from vLLM server.",
        examples=[["qwen2.5-7b-instruct"]],
    )
    models_error: str | None = Field(
        default=None,
        description="Error message if models query failed.",
    )


class LLMStatus(BaseModel):
    """AI/LLM provider configuration and diagnostics."""

    config: dict[str, Any] = Field(
        ...,
        description="Sanitized AI configuration.",
    )
    vllm: VLLMInfo | None = Field(
        default=None,
        description="vLLM-specific information (if provider is vllm).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "config": {
                    "provider": "vllm",
                    "model_name": "qwen2.5-7b-instruct",
                    "api_key": "***",
                },
                "vllm": {
                    "version": "0.6.0",
                    "models": ["qwen2.5-7b-instruct"],
                },
            }
        }
    )


class BuildStatus(BaseModel):
    """Build and runtime metadata."""

    app_name: str = Field(
        ...,
        description="Application name.",
        examples=["agent-service"],
    )
    app_version: str = Field(
        ...,
        description="Application version.",
        examples=["1.0.0"],
    )
    environment: str = Field(
        ...,
        description="Current environment name.",
        examples=["development", "production"],
    )
    python_version: str = Field(
        ...,
        description="Python runtime version.",
        examples=["3.12.0"],
    )
    platform: str = Field(
        ...,
        description="Operating system platform.",
        examples=["Linux-5.15.0-x86_64"],
    )
    settings_files: list[str] = Field(
        ...,
        description="Configuration files loaded.",
        examples=[["/app/settings.toml", "/app/.secrets.toml"]],
    )
    build_commit: str = Field(
        ...,
        description="Git commit hash of the build.",
        examples=["abc123def456"],
    )
    build_timestamp: str = Field(
        ...,
        description="Build timestamp.",
        examples=["2025-10-09T20:00:00Z"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "app_name": "agent-service",
                "app_version": "1.0.0",
                "environment": "development",
                "python_version": "3.12.0",
                "platform": "Linux-5.15.0-x86_64",
                "settings_files": ["/app/settings.toml"],
                "build_commit": "abc123def456",
                "build_timestamp": "2025-10-09T20:00:00Z",
            }
        }
    )
