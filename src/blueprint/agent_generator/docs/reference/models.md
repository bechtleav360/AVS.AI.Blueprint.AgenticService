# Data Models Reference

Pydantic models used throughout the Blueprint Agents framework for events, configuration, and API responses.

---

## CloudEvent[T]

**Module:** `blueprint.agents.models.events`

Generic CloudEvents-compliant envelope. The type parameter `T` defines the payload type of the `data` field.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique event identifier. |
| `type` | `str` | Event type identifier (e.g., `"order.created.v1"`). |
| `specversion` | `str` | CloudEvents specification version. |
| `source` | `str` | URI identifying the event source. |
| `subject` | `str \| None` | Optional subject or entity the event relates to. |
| `time` | `str \| None` | Timestamp of the event in RFC 3339 format. |
| `datacontenttype` | `str \| None` | Content type of the `data` field (e.g., `"application/json"`). |
| `data` | `T` | Event payload. Type depends on the generic parameter. |
| `topic` | `str \| None` | Topic the event was published to or received from. |

---

## GenericCloudEvent

**Module:** `blueprint.agents.models.events`

Type alias for `CloudEvent[dict[str, Any]]`. Use this when the event payload is an arbitrary dictionary.

```python
GenericCloudEvent = CloudEvent[dict[str, Any]]
```

---

## HandlerResult

**Module:** `blueprint.agents.models.events`

Returned from event handlers to publish follow-up events.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `event_type` | `str \| None` | `None` | Type of the outbound event. |
| `subject` | `str \| None` | `None` | Subject for the outbound event. |
| `data` | `dict \| None` | `None` | Payload data for the outbound event. |
| `metadata` | `dict \| None` | `None` | Additional metadata attached to the outbound event. |

---

## AIConfig

**Module:** `blueprint.agents.models.config`

Model provider and runtime settings resolved from a `[default.runtimes.<name>]` configuration section.

| Field | Type | Description |
|-------|------|-------------|
| `provider` | `str` | Model provider (`"openai"`, `"vllm"`). |
| `model_name` | `str` | Model identifier. |
| `api_key` | `str` | API key for the provider. |
| `base_url` | `str \| None` | Base URL for the model API. |
| `model_settings` | `dict \| None` | Additional provider-specific model settings. |
| `max_tokens` | `int \| None` | Maximum response tokens. |
| `temperature` | `float \| None` | Sampling temperature. |
| `concurrency_limit` | `int \| None` | Maximum concurrent requests. |
| `usage_limits` | `dict \| None` | Token and request usage limits. |

---

## CacheConfig

**Module:** `blueprint.agents.models.config`

Disk cache settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cache_dir` | `str` | `".cache/blueprint"` | Directory for cache files. |
| `size_limit` | `int` | `1000000000` | Maximum cache size in bytes. |
| `eviction_policy` | `str` | `"least-recently-used"` | Eviction strategy. |
| `default_ttl` | `int` | `3600` | Default entry TTL in seconds. |

---

## EventPublishingConfig

**Module:** `blueprint.agents.models.config`

Event publishing and topic routing settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_pubsub_name` | `str` | `"pubsub"` | Default pub/sub component name. |
| `topic_mapping` | `dict` | `{}` | Map of event type to topic name. |

---

## ObservabilityConfig

**Module:** `blueprint.agents.models.config`

OpenTelemetry and logging configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `otel_enabled` | `bool` | `False` | Whether OpenTelemetry export is enabled. |
| `otel_endpoint` | `str \| None` | `None` | OTLP collector endpoint. |
| `otel_service_name` | `str \| None` | `None` | Service name for telemetry. |
| `log_level` | `str` | `"INFO"` | Log level for the application. |

---

## PromptConfig

**Module:** `blueprint.agents.models.config`

Prompt template resolution settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `custom_path` | `str \| None` | `None` | Primary prompt directory path. |
| `search_paths` | `list[str]` | `[]` | Additional directories to search for prompts. |
| `system_prompt_name` | `str` | `"system"` | Filename of the system prompt template. |
| `instruction_prompt_name` | `str` | `"instruction"` | Filename of the instruction prompt template. |

---

## ProcessResourceResponse

**Module:** `blueprint.agents.models`

Standard API response envelope for resource processing operations.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `success` | `bool` | -- | Whether the operation succeeded. |
| `request_id` | `str` | -- | Unique identifier for the request. |
| `message` | `str` | -- | Human-readable status message. |
| `data` | `Any` | `None` | Optional response payload. |
