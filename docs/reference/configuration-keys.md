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
| `dapr_pubsub_name` | `str` | `"pubsub"` | Dapr pub/sub component name, used when publishing and in the subscription document served at `GET /dapr/subscribe`. Only used when `event_bus = "dapr"`. |
| `dapr_declarative_subscriptions` | `bool` | `false` | Set `true` when Dapr subscriptions are declared outside the application (Kubernetes `Subscription` resources or YAML). The discovery endpoint then serves an empty document, so the sidecar cannot subscribe twice. |
| `nats_queue_group` | `str` | value of `app_name` | Queue group joined by every NATS subscription, so exactly one replica processes any given message. Identifies the agent, not the process: it must not contain a pod, container or replica name, or moving the agent between deployments would change which consumer it is. Startup fails if neither this key nor `app_name` yields a name. Applies to the root namespace only -- a client that belongs to a namespace uses the namespace name, so two agents sharing a process never share a group. Only used when `event_bus = "nats"`. |
| `event_client_max_retries` | `int` | `-1` | Number of reconnection attempts if the broker is unavailable at startup. `-1` retries indefinitely until the broker becomes reachable. `0` makes a single attempt and logs a permanent error on failure. |
| `event_client_retry_delay` | `float` | `5.0` | Seconds to wait between reconnection attempts. |
| `event_client_drain_timeout` | `float` | `30.0` | Seconds allowed at shutdown for in-flight message handlers to finish before the broker connection is closed. Bounds the whole shutdown sequence, so keep it below the pod's termination grace period. |
| `nats_use_jetstream` | `bool` | `false` | Consume through a durable JetStream consumer instead of Core NATS. The keys below apply only when this is `true`. |
| `nats_stream_name` | `str` | `"EVENTS"` | Stream the durable consumers are created on. The framework creates it if it is missing, and widens an existing one to cover every subscribed subject plus the dead-letter subject; it never removes a subject. |
| `nats_durable_name` | `str` | `"<topic>-durable"` | Name of the durable consumer. Derived from the topic by default, with `.`, `*`, `>` and whitespace replaced by `_` because NATS rejects them in a consumer name. A client that belongs to a namespace prefixes it (`"<namespace>-<topic>-durable"`), so two agents subscribing to the same topic get a consumer each. Setting it explicitly is only valid with a single subscribed topic: a durable filters one subject, and under a namespace it must be scoped per namespace or every namespace binds to the same consumer. |
| `nats_ack_wait` | `float` | `300.0` | Seconds the broker waits for an acknowledgement before redelivering. **Must exceed the p99 duration of your slowest handler**, or long inference is redelivered to another replica while the first is still working. The default is deliberately far above the NATS default of 30 s because handlers in this framework call models. |
| `nats_max_ack_pending` | `int` | `16` | Unacknowledged messages the consumer may have outstanding at once, counted across every replica sharing it. `-1` is unlimited. Keep it close to the number of replicas: a push subscription runs its callbacks one at a time, so anything much larger queues messages inside the client while their `nats_ack_wait` is already running down. |
| `nats_max_deliver` | `int` | `5` | Delivery attempts before the message is dead-lettered. `-1` is unlimited, which means a permanently failing message is retried forever and never dead-lettered; the client logs a warning at startup if you set it. |
| `nats_dead_letter_subject` | `str` | `"<nats_queue_group>.dead-letter"` | Subject a message is republished to when the framework gives up on it -- either a terminal failure (`InvalidEventError`, `CriticalHandlerError`, or a payload that is not a CloudEvent) or `nats_max_deliver` attempts spent. The original bytes are republished unchanged, with `Blueprint-Dead-Letter-Reason`, `Blueprint-Original-Subject`, `Blueprint-Delivery-Count` and `Blueprint-Event-Id` headers. Set to `""` to disable, which drops those messages and loses their payloads. Startup fails if the subject is a wildcard or is itself one of the subscribed subjects, since that would loop. |

---

## Deployment Identity (environment only)

These are read straight from the environment, not from `settings.toml`, and carry the
`BLUEPRINT_` prefix rather than Dynaconf's. They describe *where* the process runs, so they
are used for the NATS connection name and for nothing else: no queue group, durable name or
dead-letter subject may be derived from them, or moving an agent between deployments would
change which broker-side consumer it is.

| Variable | Default | Description |
|-----|---------|-------------|
| `BLUEPRINT_GROUP` | `<ungrouped>` in the connection name | Deployment group this process was started as. Appears in the middle position of the NATS connection name. |
| `POD_NAME` | -- | Replica identity, preferred over `HOSTNAME` because a deployment can set it explicitly through the Kubernetes downward API. Appears in the last position of the connection name. |
| `HOSTNAME` | the host name, else `<unknown-pod>` | Used when `POD_NAME` is unset; the kubelet sets it to the pod name. |

Every NATS connection is named `<namespace>.<group>.<pod>`, which is what makes a pod's
contents legible in the broker's `/connz` output. The namespace segment is `<root>` for an
application that never names one -- that is, for every single-agent application.

An absent value becomes a bracketed placeholder rather than an empty segment, so a name never
degenerates into `..pod-7`. The brackets are not decoration: they are excluded from the namespace
alphabet (below), so no real namespace can spell one. Because a group name and a pod name come
from the deployment and are not rejected on that ground, they are instead sanitised for display --
`<`, `>`, `.` and whitespace become `_`. So a group called `eu.west` appears as `eu_west`, which
keeps the name at three segments; an FQDN in `HOSTNAME` is folded the same way. Nothing derives
from the connection name (a queue group or durable name that did would change on every restart),
so the sanitising costs nothing downstream.

### Namespace names

A namespace is the agent's name and is the only thing broker-side consumer identity derives
from, so it is validated once, where it enters the framework, and never rewritten afterwards.

| Rule | Reason |
|-----|-------------|
| `""` (root) or `[a-z][a-z0-9_]*` | The namespace becomes a registry key prefix, a NATS queue group, part of a JetStream durable name and a telemetry service name. The alphabet is the intersection of what those accept. |
| No `-` | `-` separates the fields of the durable name `<namespace>-<topic>-durable`. Allowing it makes that name ambiguous: `orders-eu` on `created` and `orders` on `eu-created` would be one consumer, so two agents would consume each other's events. Use `_`. |
| No `.`, `*`, `>` | Subject separator and wildcards; illegal in a NATS consumer name. |
| No `<`, `>` | Reserved for the connection-name placeholders above. |
| No surrounding whitespace | Not trimmed for you: the trimmed and untrimmed forms would be one agent registered under one name and subscribed under another. |

An illegal namespace fails in `Component.__init__` -- before the registry name is derived and
before registration, and for every component including those that never register. It is not
deferred to the first subscription, which a publish-only or Dapr-only agent never reaches.

### Names that become subjects are never rewritten for you

`app_name`, `nats_queue_group` and a scheduler's name all end up inside a NATS subject, a queue
group or a consumer name. Whitespace, `*` and `>` in any of them **fails startup**, naming the key,
the value and the subject that would have been derived.

This is deliberately not forgiving. `app_name = "Health Monitor"` used to be rewritten into the
tick subject `Health_Monitor.scheduler.nightly`, which is a subject the `CronJob` publishing that
tick has to spell exactly -- and whoever writes that manifest has no way to know about the rewrite.
The tick then never arrives, with nothing in either log to explain it. A name that only lives
inside the process may be repaired; a name in a contract with something outside it may not.

Two exceptions, both because nothing outside can depend on the spelling: the topic part of a
JetStream durable name (dots are legal in subjects and illegal in consumer names, so `.` becomes
`_`, and two topics colliding on one durable is an error), and the NATS connection name (see
above).

---

## Event Deduplication

Delivery is at-least-once on both transports, so a handler can be run twice for the same
event. Deduplication is opt-in and off by default: whether replaying a handler's side
effects is acceptable is a property of the product, not of the framework.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `idempotency_enabled` | `bool` | `false` | Skip an event whose `id` and `source` were already dispatched within the window. Requires `idempotency_ttl` and a registered cache (`.with_cache()`); startup fails if either is missing, rather than leaving deduplication silently off. Best-effort: the claim is check-then-set, so two replicas handed the same event at the same instant can both dispatch, and a cache error fails open. |
| `idempotency_ttl` | `int` | -- | Seconds a processed event is remembered. No default on purpose -- it must outlast the broker's redelivery window (`nats_ack_wait` * `nats_max_deliver` on JetStream, the component's retry policy under Dapr), and a window that expires before the last redelivery looks exactly like deduplication not working. |

---

## Scheduling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `scheduler_mode` | `str` | -- (**required** when a scheduler is registered) | Where a scheduler's tick comes from. `"event"` starts no in-process timer: the tick arrives as an ordinary event on the scheduler's own topic (`<app_name>.scheduler.<scheduler_name>` unless overridden with `topic=` in the scheduler's constructor), published by an external `CronJob`, so the queue group already picks exactly one replica and nothing is elected -- it requires `event_bus` to be `"dapr"` or `"nats"`, since `"sessions"` cannot deliver a topic. `"in_process"` runs an APScheduler timer inside every replica and coordinates them through the registered cache: each tick is claimed under a key derived from the scheduler and the scheduled minute, and only the replica that stores the marker runs it. Intended for local development and un-orchestrated Docker, where no `CronJob` exists. **With no cache registered the ticks cannot be coordinated and every replica runs every tick**; startup warns about it. **No default:** neither value is safe to inherit silently, and which one applies depends on the deployment (is a broker reachable, does more than one replica run, is there an orchestrator at all) rather than on the code, so the author states it -- the same reasoning as `idempotency_ttl`. An absent, empty or unrecognised value fails startup. |

---

## Event Publishing

Section: `[default.event_publishing]`

Controls how outbound events are published to topics.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `event_publishing_enabled` | `bool` | `false` | Top-level key (not in this section). Opt into publishing events **without consuming any**. A registered handler already implies a transport client, so a consuming application never needs this key; an application that only emits -- a scheduler reporting what it did, a REST API handing work on -- had no way to get a client at all before it existed. When set, the client is created and **nothing is subscribed**: no eventing endpoint, no subscription document, no `/events/{topic}` route. Off by default because publishing needs broker access a scheduler-only project may not have, and a client it never asked for becomes a readiness dependency on infrastructure it does not run. Requires `event_bus` to be `"dapr"` or `"nats"`; startup fails otherwise. |
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
| `token_metrics_enabled` | `bool` | `true` | Record LLM token usage and response latency to OpenTelemetry. Only takes effect when `otel_enabled` is also `true`. |

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
# nats_queue_group = "my_agent_service"  # defaults to app_name
event_client_max_retries = -1   # retry indefinitely
event_client_retry_delay = 5.0  # seconds between attempts
event_client_drain_timeout = 30.0  # shutdown budget for in-flight handlers

# JetStream consumer (only when nats_use_jetstream = true)
nats_use_jetstream = false
nats_stream_name = "EVENTS"
nats_ack_wait = 300.0        # must exceed the p99 handler duration
nats_max_ack_pending = 16    # outstanding messages across all replicas
nats_max_deliver = 5         # attempts before the message is dead-lettered
# nats_dead_letter_subject = "my_agent_service.dead-letter"  # defaults to <queue group>.dead-letter

# Event deduplication (off by default; both keys are needed to turn it on)
# idempotency_enabled = true
# idempotency_ttl = 1500      # seconds; must outlast the redelivery window

# Scheduling -- required once a scheduler is registered, no default
scheduler_mode = "in_process"   # or "event", which needs event_bus set
# event_publishing_enabled = true   # publish without consuming; needs event_bus

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
token_metrics_enabled = true

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
