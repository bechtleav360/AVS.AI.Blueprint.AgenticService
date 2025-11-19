"""Pydantic models for configuration objects."""

import ast
import re
from typing import Any
from pydantic import BaseModel, Field, field_validator


class TopicConfig(BaseModel):
    """Configuration for a single event topic."""

    topic: str = Field(..., description="Topic name")
    routing_key: str | None = Field(None, description="Optional routing key")


class EventPublishingConfig(BaseModel):
    """Event publishing configuration."""

    default_pubsub_name: str = Field(default="pubsub", description="Default Dapr pubsub component name")
    topic_mapping: dict[str, TopicConfig] = Field(default_factory=dict, description="Mapping of event types to topics")

    @field_validator("topic_mapping", mode="before")
    @classmethod
    def normalize_topic_mapping(cls, v: Any) -> dict[str, TopicConfig]:
        """Normalize topic mapping to TopicConfig objects."""
        if isinstance(v, str):
            v = cls._parse_mapping_string(v)

        if not isinstance(v, dict):
            raise ValueError("topic_mapping must be a dictionary")

        normalized = {}
        for event_type, topic_config in v.items():
            if isinstance(topic_config, str):
                normalized[event_type] = TopicConfig(**cls._parse_topic_config_value(topic_config))
            elif isinstance(topic_config, dict):
                normalized[event_type] = TopicConfig(**topic_config)
            elif isinstance(topic_config, TopicConfig):
                normalized[event_type] = topic_config
            else:
                raise ValueError(f"Invalid topic mapping for event type '{event_type}': {topic_config}")

        return normalized

    @staticmethod
    def _parse_mapping_string(value: str) -> dict[str, Any]:
        """Parse mapping provided as a single string (e.g. from env vars)."""

        cleaned = value.strip()
        if not cleaned:
            return {}

        if cleaned.startswith("{") and cleaned.endswith("}"):
            # Quote inner keys like `topic` or `routing_key` that may lack quotes
            pattern = re.compile(r"(\{|,)\s*([A-Za-z_][\w.\-]*)\s*:")

            def _quote_keys(match: re.Match[str]) -> str:
                prefix, key = match.groups()
                return f"{prefix} '{key}':"

            normalized = pattern.sub(_quote_keys, cleaned)

            try:
                parsed = ast.literal_eval(normalized)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(f"Invalid topic mapping string: {value}") from exc

            if not isinstance(parsed, dict):
                raise ValueError("Parsed topic mapping must be a dictionary")

            return parsed

        raise ValueError(f"Unsupported topic mapping format: {value}")

    @staticmethod
    def _parse_topic_config_value(value: str) -> dict[str, Any]:
        """Parse a single topic config value from a string."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("Topic config value cannot be empty")

        if stripped.startswith("map[") and stripped.endswith("]"):
            inner = stripped[4:-1].strip()
            if not inner:
                raise ValueError("Empty map[] topic configuration")

            parts = re.split(r"\s+", inner)
            result: dict[str, str] = {}
            for part in parts:
                if not part:
                    continue
                if ":" not in part:
                    raise ValueError(f"Invalid map[] entry: {part}")
                key, val = part.split(":", 1)
                result[key] = val

            if "topic" not in result:
                raise ValueError("map[] topic configuration must include a 'topic' entry")

            return result

        return {"topic": stripped}


class UsageLimits(BaseModel):
    """AI model usage limits."""

    request_limit: int | None = Field(None, description="Max requests")
    input_tokens_limit: int | None = Field(None, description="Max input tokens")
    output_tokens_limit: int | None = Field(None, description="Max output tokens")
    total_tokens_limit: int | None = Field(None, description="Max total tokens")


class AIConfig(BaseModel):
    """AI model configuration."""

    provider: str | None = Field(None, description="AI provider (e.g., 'openai', 'vllm')")
    model_name: str | None = Field(None, description="Model name")
    api_key: str | None = Field(None, description="API key")
    base_url: str | None = Field(None, description="Base URL for API")
    max_tokens: int | None = Field(None, description="Max tokens per request")
    temperature: float | None = Field(None, description="Temperature for generation")
    concurrency_limit: int | None = Field(None, description="Max concurrent requests")
    usage_limits: UsageLimits = Field(default_factory=UsageLimits, description="Usage limits")


class PromptConfig(BaseModel):
    """Prompt configuration."""

    prompts: dict[str, str] = Field(default_factory=dict, description="Prompt content by name (highest priority)")
    custom_path: str | None = Field(None, description="Custom path to prompts")
    search_paths: list[str] = Field(default_factory=list, description="Additional search paths")
    system_prompt_name: str = Field(default="system", description="System prompt file name")
    instruction_prompt_name: str = Field(default="instruction", description="Instruction prompt file name")


class ObservabilityConfig(BaseModel):
    """Observability configuration."""

    otel_enabled: bool = Field(default=False, description="Enable OpenTelemetry")
    otel_endpoint: str | None = Field(None, description="OpenTelemetry endpoint")
    otel_service_name: str = Field(default="agent-service", description="OpenTelemetry service name")
    token_metrics_enabled: bool = Field(default=True, description="Enable token usage and latency metrics")
    log_level: str = Field(default="INFO", description="Log level")


class RuntimeConfig(BaseModel):
    """Runtime-specific configuration."""

    ai_model_provider: str | None = Field(None, description="AI provider override")
    ai_model_name: str | None = Field(None, description="Model name override")
    ai_model_api_key: str | None = Field(None, description="API key override")
    ai_model_base_url: str | None = Field(None, description="Base URL override")
    ai_model_max_tokens: int | None = Field(None, description="Max tokens override")
    ai_model_temperature: float | None = Field(None, description="Temperature override")
    ai_concurrent_requests: int | None = Field(None, description="Concurrency limit override")
    prompt_directory: str | None = Field(None, description="Prompt directory override")
    prompt_search_paths: list[str] | None = Field(None, description="Prompt search paths override")

    class Config:
        """Pydantic config."""

        extra = "allow"  # Allow additional fields for extensibility
