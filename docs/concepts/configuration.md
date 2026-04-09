# Configuration

Blueprint Agents uses a layered configuration system built on Dynaconf. Configuration is loaded from TOML files, with support for environment variable interpolation, environment-specific overrides, and structured sections for each framework subsystem.

## Config Class

The `Config` class is the entry point for all configuration. It accepts a list of settings files and merges them in order, with later files overriding earlier ones.

```python
from blueprint.agents import Config

config = Config(settings_files=["settings.toml", "secrets.toml"])
```

The `Config` instance is passed to `AppBuilder` and automatically made available to all components via `self.config`.

## File Structure

### settings.toml

The primary configuration file. All settings live under a `[default]` section (the Dynaconf default environment).

```toml
[default]
app_name = "document-processor"
log_level = "INFO"
event_bus = "dapr"
```

### secrets.toml

A separate file for sensitive values such as API keys, connection strings, and credentials. This file should be listed in `.gitignore` and never committed to version control.

```toml
[default]
openai_api_key = "sk-..."
database_connection_string = "postgresql://user:pass@host/db"
```

## Environment Variable Interpolation

Any value in a TOML file can reference an environment variable using the `${ENV_VAR}` syntax. This is useful for deployment environments where secrets are injected through the platform.

```toml
[default]
openai_api_key = "${OPENAI_API_KEY}"
nats_url = "${NATS_URL}"
database_url = "${DATABASE_URL}"
```

If the environment variable is not set, Dynaconf will raise an error at startup.

## Configuration Sections

### AI Runtime Configuration

Each registered agent runtime has its own configuration block under `[default.runtimes.<name>]`. The name must match the name used in `.with_agent(name, ...)`.

```toml
[default.runtimes.summarizer]
model_provider = "openai"
model_name = "gpt-4o"
model_api_key = "${OPENAI_API_KEY}"
model_max_tokens = 4096
model_temperature = 0.3
model_base_url = "https://api.openai.com/v1"

[default.runtimes.classifier]
model_provider = "anthropic"
model_name = "claude-sonnet-4-20250514"
model_api_key = "${ANTHROPIC_API_KEY}"
model_max_tokens = 2048
model_temperature = 0.0
```

### Cache Configuration

Settings for the built-in disk cache service, under `[default.cache]`.

```toml
[default.cache]
cache_dir = "/tmp/blueprint-cache"
size_limit = 1073741824          # 1 GB in bytes
eviction_policy = "least-recently-used"
default_ttl = 3600               # seconds
```

See the [Caching](caching.md) concept document for full details.

### Event Publishing Configuration

Controls how events are published, including the default pub/sub component and topic-to-event-type mappings.

```toml
[default.event_publishing]
default_pubsub_name = "pubsub"

[default.event_publishing.topic_mapping]
"document.received" = "documents-inbound"
"document.summarized" = "documents-processed"
"document.error" = "documents-errors"
```

See the [Event Processing](event-processing.md) concept document for full details.

### Observability Configuration

Settings for OpenTelemetry tracing and structured logging.

```toml
[default]
otel_enabled = true
otel_endpoint = "http://localhost:4317"
otel_service_name = "document-processor"
log_level = "INFO"
```

See the [Observability](observability.md) concept document for full details.

## Accessing Configuration at Runtime

All components inherit access to configuration through `self.config`, which is available from `on_startup()` onward.

### General Access

```python
from blueprint.agents.services.service_base import ServiceBase


class StorageService(ServiceBase):
    async def on_startup(self) -> None:
        # Read a single value
        db_url = self.config.get("database_url")

        # Read a value with a default
        timeout = self.config.get("request_timeout", 30)
```

### AI Runtime Configuration

Use `get_ai_config()` to retrieve the full configuration block for a named runtime. This returns a structured object with all model-related settings.

```python
from blueprint.agents.services.service_base import ServiceBase


class ModelService(ServiceBase):
    async def on_startup(self) -> None:
        ai_config = self.config.get_ai_config("summarizer")

        provider = ai_config.model_provider      # "openai"
        model = ai_config.model_name              # "gpt-4o"
        max_tokens = ai_config.model_max_tokens   # 4096
        temperature = ai_config.model_temperature # 0.3
```

### Cache Configuration

Use `get_cache_config()` to retrieve cache-related settings as a structured object.

```python
cache_config = self.config.get_cache_config()
print(cache_config.cache_dir)        # "/tmp/blueprint-cache"
print(cache_config.size_limit)       # 1073741824
print(cache_config.eviction_policy)  # "least-recently-used"
print(cache_config.default_ttl)      # 3600
```

## Validation

Configuration is validated automatically when `AppBuilder.build()` is called. If required settings are missing or have invalid types, a `ConfigError` is raised with a descriptive message.

```python
from blueprint.agents import AppBuilder, Config

config = Config(settings_files=["settings.toml"])

try:
    app = AppBuilder(config).with_agent("summarizer", SummarizerAgent).build()
except ConfigError as e:
    # e.g., "Missing required config: default.runtimes.summarizer.model_provider"
    print(f"Configuration error: {e}")
```

Validation checks include:

- Required fields for each registered runtime (model_provider, model_name)
- Valid event bus selection ("dapr" or "nats")
- Topic mappings exist for all declared published event types
- Cache configuration is present when `.with_cache()` is used

## Full Example settings.toml

```toml
[default]
app_name = "document-processor"
log_level = "INFO"
event_bus = "dapr"

# Observability
otel_enabled = true
otel_endpoint = "http://localhost:4317"
otel_service_name = "document-processor"

# Event publishing
[default.event_publishing]
default_pubsub_name = "pubsub"

[default.event_publishing.topic_mapping]
"document.received" = "documents-inbound"
"document.summarized" = "documents-processed"
"document.error" = "documents-errors"

# AI runtimes
[default.runtimes.summarizer]
model_provider = "openai"
model_name = "gpt-4o"
model_api_key = "${OPENAI_API_KEY}"
model_max_tokens = 4096
model_temperature = 0.3

[default.runtimes.classifier]
model_provider = "anthropic"
model_name = "claude-sonnet-4-20250514"
model_api_key = "${ANTHROPIC_API_KEY}"
model_max_tokens = 2048
model_temperature = 0.0

# Cache
[default.cache]
cache_dir = "/tmp/blueprint-cache"
size_limit = 1073741824
eviction_policy = "least-recently-used"
default_ttl = 3600
```
