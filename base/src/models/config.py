"""Pydantic models for configuration objects."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator


class TopicConfig(BaseModel):
    """Configuration for a single event topic."""

    topic: str = Field(..., description="Topic name")
    routing_key: Optional[str] = Field(None, description="Optional routing key")


class EventPublishingConfig(BaseModel):
    """Event publishing configuration."""

    default_pubsub_name: str = Field(default="pubsub", description="Default Dapr pubsub component name")
    topic_mapping: Dict[str, TopicConfig] = Field(default_factory=dict, description="Mapping of event types to topics")

    @field_validator("topic_mapping", mode="before")
    @classmethod
    def normalize_topic_mapping(cls, v: Any) -> Dict[str, TopicConfig]:
        """Normalize topic mapping to TopicConfig objects."""
        if not isinstance(v, dict):
            raise ValueError("topic_mapping must be a dictionary")

        normalized = {}
        for event_type, topic_config in v.items():
            if isinstance(topic_config, str):
                normalized[event_type] = TopicConfig(topic=topic_config)
            elif isinstance(topic_config, dict):
                normalized[event_type] = TopicConfig(**topic_config)
            elif isinstance(topic_config, TopicConfig):
                normalized[event_type] = topic_config
            else:
                raise ValueError(f"Invalid topic mapping for event type '{event_type}': {topic_config}")

        return normalized


class UsageLimits(BaseModel):
    """AI model usage limits."""

    request_limit: Optional[int] = Field(None, description="Max requests")
    input_tokens_limit: Optional[int] = Field(None, description="Max input tokens")
    output_tokens_limit: Optional[int] = Field(None, description="Max output tokens")
    total_tokens_limit: Optional[int] = Field(None, description="Max total tokens")


class AIConfig(BaseModel):
    """AI model configuration."""

    provider: Optional[str] = Field(None, description="AI provider (e.g., 'openai', 'vllm')")
    model_name: Optional[str] = Field(None, description="Model name")
    api_key: Optional[str] = Field(None, description="API key")
    base_url: Optional[str] = Field(None, description="Base URL for API")
    max_tokens: Optional[int] = Field(None, description="Max tokens per request")
    temperature: Optional[float] = Field(None, description="Temperature for generation")
    concurrency_limit: Optional[int] = Field(None, description="Max concurrent requests")
    usage_limits: UsageLimits = Field(default_factory=UsageLimits, description="Usage limits")


class PromptConfig(BaseModel):
    """Prompt configuration."""

    custom_path: Optional[str] = Field(None, description="Custom path to prompts")
    search_paths: list[str] = Field(default_factory=list, description="Additional search paths")
    system_prompt_name: str = Field(default="system", description="System prompt file name")
    instruction_prompt_name: str = Field(default="instruction", description="Instruction prompt file name")


class ObservabilityConfig(BaseModel):
    """Observability configuration."""

    otel_enabled: bool = Field(default=False, description="Enable OpenTelemetry")
    otel_endpoint: Optional[str] = Field(None, description="OpenTelemetry endpoint")
    otel_service_name: str = Field(default="agent-service", description="OpenTelemetry service name")
    log_level: str = Field(default="INFO", description="Log level")


class RuntimeConfig(BaseModel):
    """Runtime-specific configuration."""

    ai_model_provider: Optional[str] = Field(None, description="AI provider override")
    ai_model_name: Optional[str] = Field(None, description="Model name override")
    ai_model_api_key: Optional[str] = Field(None, description="API key override")
    ai_model_base_url: Optional[str] = Field(None, description="Base URL override")
    ai_model_max_tokens: Optional[int] = Field(None, description="Max tokens override")
    ai_model_temperature: Optional[float] = Field(None, description="Temperature override")
    ai_concurrent_requests: Optional[int] = Field(None, description="Concurrency limit override")
    prompt_directory: Optional[str] = Field(None, description="Prompt directory override")
    prompt_search_paths: Optional[list[str]] = Field(None, description="Prompt search paths override")

    class Config:
        """Pydantic config."""

        extra = "allow"  # Allow additional fields for extensibility
