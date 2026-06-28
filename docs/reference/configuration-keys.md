# Configuration Keys Reference

Complete reference for all `settings.toml` configuration keys in the Blueprint Agents framework.

Settings are loaded from `settings.toml` (and optional environment-specific overrides). Environment variables can override any key using the prefix `BLUEPRINT_` with double-underscore separators (e.g., `BLUEPRINT_APP_PORT=9000`).

---

## Application

Top-level application settings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `app_name` | `str` | `"agent_blueprint"` | Application name. Used in logging, health checks, and OpenTelemetry service identification. |
| `app_port` | `int` | `8000` | HTTP port the application listens on. |
| `app_environment` | `str` | `"development"` | Deployment environment identifier (e.g., `"development"`, `"staging"`, `"production"`). |
| `log_level` | `str` | `"INFO"` | Root log level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `log_format` | `str` | `"text"` | Log output format. `"text"` for human-readable, `"json"` for structured JSON logging. |

---

## Event Bus

Settings for the event bus transport layer.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `event_bus` | `str` | `""` | Event bus implementation. Set to `"dapr"` for Dapr pub/sub or `"nats"` for NATS. Empty string disables the event bus. |
| `nats_url` | `str` | `"nats://localhost:4222"` | NATS server URL. Only used when `event_bus = "nats"`. |
| `event_client_max_retries` | `int` | `-1` | Number of reconnection attempts if the broker is unavailable at startup. `-1` retries indefinitely until the broker becomes reachable. `0` makes a single attempt and logs a permanent error on failure. |
| `event_client_retry_delay` | `float` | `5.0` | Seconds to wait between reconnection attempts. |

---

## Event Publishing

Section: `[default.event_publishing]`

Controls how outbound events are published to topics.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_pubsub_name` | `str` | `"pubsub"` | Default pub/sub component name (used with Dapr). |
| `topic_mapping` | `dict` | `{}` | Maps event type strings to topic names. Events not in this mapping use the event type as the topic. |

---

## AI / Model Runtime

Section: `[default.runtimes.<name>]`

Each named runtime defines model provider settings. The `default` runtime is used when no name is specified.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model_provider` | `str` | -- | Model provider. `"openai"` for OpenAI-compatible APIs, `"vllm"` for vLLM endpoints. |
| `model_name` | `str` | -- | Model identifier (e.g., `"gpt-4o"`, `"meta-llama/Llama-3-70b"`). |
| `model_api_key` | `str` | -- | API key for the model provider. Can also be set via environment variable. |
| `model_base_url` | `str` | -- | Base URL for the model API. Required for `"vllm"` and custom OpenAI-compatible endpoints. |
| `model_max_tokens` | `int` | -- | Maximum number of tokens in the model response. |
| `model_temperature` | `float` | -- | Sampling temperature. Lower values produce more deterministic output. |
| `concurrent_requests` | `int` | -- | Maximum number of concurrent requests to the model provider. |

---

## Prompts

Top-level settings for prompt file resolution.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `prompt_directory` | `str` | -- | Primary directory containing prompt template files. |
| `prompt_search_paths` | `list[str]` | `[]` | Additional directories to search for prompt files, in order. |
| `system_prompt_name` | `str` | `"system"` | Filename (without extension) of the system prompt template. |
| `instruction_prompt_name` | `str` | `"instruction"` | Filename (without extension) of the instruction prompt template. |

---

## Cache

Section: `[default.cache]`

Disk cache settings used when `with_cache()` is enabled on the `AppBuilder`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `cache_dir` | `str` | `".cache/blueprint"` | Directory for cache storage. |
| `size_limit` | `int` | `1000000000` | Maximum cache size in bytes (default ~1 GB). |
| `eviction_policy` | `str` | `"least-recently-used"` | Cache eviction policy. |
| `default_ttl` | `int` | `3600` | Default time-to-live for cache entries in seconds. |

---

## Observability

OpenTelemetry and tracing settings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `otel_enabled` | `bool` | `false` | Enable OpenTelemetry tracing and metrics export. |
| `otel_endpoint` | `str` | -- | OTLP collector endpoint URL (e.g., `"http://localhost:4317"`). |
| `otel_service_name` | `str` | -- | Service name reported to the OTLP collector. Defaults to `app_name` if not set. |

---

## Logging

Additional logging behavior settings.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `suppress_noisy_loggers` | `bool` | `true` | Suppress verbose log output from third-party libraries (e.g., `httpx`, `httpcore`). |

---

## Example settings.toml

```toml
# Application
app_name = "my_agent_service"
app_port = 8000
app_environment = "development"
log_level = "INFO"
log_format = "text"

# Event Bus
event_bus = "nats"
nats_url = "nats://localhost:4222"
event_client_max_retries = -1   # retry indefinitely
event_client_retry_delay = 5.0  # seconds between attempts

# Prompts
prompt_directory = "prompts"
prompt_search_paths = ["shared/prompts"]
system_prompt_name = "system"
instruction_prompt_name = "instruction"

# Logging
suppress_noisy_loggers = true

# Observability
otel_enabled = false
otel_endpoint = "http://localhost:4317"
otel_service_name = "my_agent_service"

[default.event_publishing]
default_pubsub_name = "pubsub"

[default.event_publishing.topic_mapping]
"order.created.v1" = "orders"
"order.completed.v1" = "orders"

[default.runtimes.default]
model_provider = "openai"
model_name = "gpt-4o"
model_api_key = "@format {this.OPENAI_API_KEY}"
model_max_tokens = 4096
model_temperature = 0.7
concurrent_requests = 5

[default.runtimes.fast]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_api_key = "@format {this.OPENAI_API_KEY}"
model_max_tokens = 2048
model_temperature = 0.3
concurrent_requests = 10

[default.cache]
cache_dir = ".cache/blueprint"
size_limit = 1000000000
eviction_policy = "least-recently-used"
default_ttl = 3600
```
