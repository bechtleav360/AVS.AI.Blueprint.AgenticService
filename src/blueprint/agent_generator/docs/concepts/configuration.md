# Configuration

Blueprint Agents uses a layered configuration system built on Dynaconf. Configuration is loaded from TOML files, with environment variable overrides, environment-specific sections, and structured sections for each framework subsystem.

## Config Class

The `Config` class is the entry point for all configuration. It accepts a list of settings files and merges them in order, with later files overriding earlier ones.

```python
from blueprint.agents import Config

config = Config(settings_files=["settings.toml", ".secrets.toml"])
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

### .secrets.toml

A separate file for sensitive values such as API keys, connection strings, and credentials. This file should be listed in `.gitignore` and never committed to version control.

```toml
[default]
model_api_key = "YOUR_API_KEY_HERE"
database_connection_string = "postgresql://USER:PASSWORD@HOST/DB"
```

## Values from the Environment

The framework does **no** `${ENV_VAR}` interpolation: `nats_url = "${NATS_URL}"` is read as that
literal string. There are two ways to take a value from the environment:

- **Override the key.** `DYNACONF_<KEY>` replaces the key outright (`DYNACONF_NATS_URL`,
  `DYNACONF_MODEL_API_KEY`); an `envvar_prefix` adds a second spelling. See
  [configuration keys](../reference/configuration-keys.md) for the prefix and for nested keys.
- **Dynaconf's `@format` token**, inside the file:

```toml
[default]
nats_url = "@format {env[NATS_URL]}"
```

## Configuration Sections

### AI Runtime Configuration

Each agent runtime has its own configuration block under `[default.runtimes.<name>]`. The name must match the `runtime_name` given to `AgentBuilder`. A key the block leaves out falls back to the same key at the top level, so a shared `model_api_key` can live once in `.secrets.toml`.

```toml
[default.runtimes.summarizer]
model_provider = "openai"
model_name = "gpt-4o"
model_max_tokens = 4096
model_temperature = 0.3
model_base_url = "https://api.openai.com/v1"

[default.runtimes.classifier]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_max_tokens = 2048
model_temperature = 0.0
```

`model_provider` is `"openai"` or `"vllm"`; any other value is refused when the runtime is built.

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

Use `get_ai_config()` to retrieve the full configuration block for a named runtime. This returns an `AIConfig` with the model settings, the top-level fallback already applied.

```python
from blueprint.agents.services.service_base import ServiceBase


class ModelService(ServiceBase):
    async def on_startup(self) -> None:
        ai_config = self.config.get_ai_config("summarizer")

        provider = ai_config.provider          # "openai"
        model = ai_config.model_name           # "gpt-4o"
        max_tokens = ai_config.max_tokens      # 4096
        temperature = ai_config.temperature    # 0.3
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

There is no schema check up front. Each part of the framework checks what it reads, when it reads it -- most of it in `AppBuilder.build()` and during startup -- and fails with a message naming the key. `Config(...)` itself raises `ConfigError` (`blueprint.agents.config.config`) for what it checks on load -- an `app_port` outside 1-65535, a `vllm` default runtime without an API key -- and so does an agent's settings file that cannot be read; a runtime without a model name or provider raises `ValueError` from `build()`.

```python
from blueprint.agents import AgentBuilder, AppBuilder, Config
from blueprint.agents.config.config import ConfigError

summarizer = AgentBuilder(runtime_name="summarizer").with_model_from_config()
agent = AppBuilder().with_agent(summarizer, name="summarizer")

try:
    app = agent.build(Config(settings_files=["settings.toml"]))
except (ConfigError, ValueError) as e:
    # e.g., "No model name for runtime agent 'summarizer' configured"
    print(f"Configuration error: {e}")
```

Among the checks: each runtime's model name and provider; `event_bus` (`"dapr"`, `"nats"` or `"sessions"`) against what the application needs, such as a transport that can carry a scheduler's tick; `scheduler_mode` where a scheduler is registered; `idempotency_ttl` and a cache where deduplication is on. `asbs validate` runs the static ones without starting anything -- see [validate](../guides/cli/validate.md).

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
# model_api_key lives in .secrets.toml, or comes from DYNACONF_MODEL_API_KEY
[default.runtimes.summarizer]
model_provider = "openai"
model_name = "gpt-4o"
model_max_tokens = 4096
model_temperature = 0.3

[default.runtimes.classifier]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_max_tokens = 2048
model_temperature = 0.0

# Cache
[default.cache]
cache_dir = "/tmp/blueprint-cache"
size_limit = 1073741824
eviction_policy = "least-recently-used"
default_ttl = 3600
```

---

## Where an agent's settings file lives

**Beside `src/`, in the agent's own directory.** The same place whether the agent runs alone or
as one of twenty -- that sameness is what lets the directory move between its own repository
and a group image untouched.

```
my_agent/
  settings.toml      <- here
  .secrets.toml
  src/
    main.py
    prompts/
```

In a group, the image's `agents.toml` states that directory with `root`, and the file is merged
under the agent's own scope -- so the agent keeps writing plain keys and never learns that a
scope exists. The agent's `.secrets.toml` beside it is merged the same way, first, so a key both
files set takes the secrets file's value; no value from it is ever logged. What the group's own
configuration already says for the agent -- a `[default.<agent>]` section in the image's
settings, or an environment override such as `DYNACONF_<AGENT>__<KEY>` -- wins over both. It is **stated, never derived**: a root guessed from where the declaration module
happens to sit is right for one layout and silently wrong for every other, and an agent whose
settings file was looked for in the wrong place does not fail. It runs on the group's defaults
and says nothing.

A `settings.toml` inside `src/` is **refused**, not ignored, for that reason.

### Names an agent cannot have

An agent's settings live under its name at the top of the tree, so a few names are taken:

- **`cache`, `event_publishing`, `runtimes` and `runtime`** -- the sections the whole process
  shares. An agent of that name is refused.
- **A plain key of the group's own configuration.** If the image's settings set `orders = "..."`
  as a value rather than a section, an agent called `orders` with settings of its own is refused
  at merge, because merging would replace that value for the whole process.

And through its configuration view an agent reads only its own keys and the shared ones: a bare
key that is another agent's name (`self.config.get("billing")`) raises instead of returning that
agent's section, and so does a dotted key outside the shared sections.

### The file must not name its own agent

It *becomes* that agent's scope when merged, so a section named after the agent nests twice:

```toml
[default.orders]     # in the orders agent's own file -> orders.orders.*, read by nothing
```

Refused at merge, and reported by `asbs validate --group`. Write the keys at the top level or under
a plain `[default]`; that form resolves standalone as well, because a scoped lookup falls back to
the root key.

Environment sections are layered as Dynaconf layers the process's own: top-level keys, then
`[default]`, then the section of the active environment, then `[global]`. A table is an environment
section when it is named `development`, `production`, `staging`, `testing` or `test`, or after a
top-level table of the process's own settings files; one for another environment is dropped. Any
other top-level table is a value -- `[cache]` is this agent's cache configuration, not a scope.

### Keys an agent cannot set

Some keys describe the *process*, and one process has one of each: `app_port`, `app_host`,
`app_workers`, `app_environment`, `envvar_prefix`, `event_bus`, `log_level`, `log_format`,
`suppress_noisy_loggers`, `health_check_interval_seconds`, `startup_retry_interval_seconds`,
`readiness_policy`, `dot_placeholder`, `nats_stream_name`, `nats_connection_source`,
`nats_extra_runs_per_process`. The deployment's identity (`blueprint_group`, `pod_name`,
`hostname`) is dropped the same way.

They belong in the image's own `settings.toml`, beside `agents.toml`. Set in an agent's file
they are dropped before the merge, with a warning naming the value the process uses instead --
dropped rather than obeyed, because merging them under an agent's scope would file them where
nothing reads them. `asbs validate --group` reports them without starting anything.

A standalone agent is its own image, so its directory is both and the distinction does not
arise -- which is why the scaffolded `settings.toml` carries those keys commented out rather
than absent.

### Prompts

Resolved under the same root: `<agent>/src/prompts` and `<agent>/prompts`. Before `root` was
stated, they resolved against the *process* working directory -- one directory for a whole
group, and therefore right for at most one agent.
