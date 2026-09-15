---
name: blueprint-config
description: Configuring a Blueprint Agents service - settings.toml, .secrets.toml, per-runtime overrides, environment interpolation, and the complete key list. Use when adding or debugging any configuration key, or when startup fails on a configuration error.
user-invocable: true
---

# Blueprint Configuration

Config is Dynaconf-backed and layered: `settings.toml`, then `.secrets.toml`, then environment.

**Never guess a key name.** The complete list ships with the package - read it:

```bash
asbs docs reference/configuration-keys --cat   # every key, grouped by subsystem
asbs docs concepts/configuration --cat         # the Config class, layering, interpolation
```

The reference groups keys under: Application, Event Bus, Deployment Identity (environment only),
Event Deduplication, Scheduling, Event Publishing, AI / Model Runtime, Prompts, Cache,
Observability, Logging.

## Shape

```toml
[default]
app_name = "my-service"
event_bus = "dapr"              # or "nats"
model_provider = "openai"
model_name = "gpt-4"

[default.runtimes.my_agent]     # per-agent overrides
model_name = "gpt-4-turbo"
model_temperature = 0.5
```

`.secrets.toml` holds `model_api_key` and the like, and is never committed.

## Keys with no safe default

These fail at startup rather than guess, so they must be set deliberately:

- **`scheduler_mode`** - required once any scheduler is registered. `"in_process"` runs an
  APScheduler timer in *every* replica and claims each tick through the cache, so it needs
  `.with_cache()` or every replica runs every tick. `"event"` starts no timer: the tick arrives as
  an event on `<app_name>.scheduler.<scheduler_name>`, so it needs `event_bus` set.
- **`idempotency_enabled` and `idempotency_ttl`** - both, or neither. Delivery is at-least-once;
  deduplication is off by default because only you know whether replaying your side effects is
  acceptable. The TTL must outlast the broker redelivery window.
- **`event_publishing_enabled`** - consuming and publishing are separate concerns. A handler implies
  a transport client; a scheduler does not.

## Reading config at runtime

Resolve configuration in `on_startup()`, never in `__init__` - `self.config` is not linked until
after construction. See *Accessing Configuration at Runtime* in `concepts/configuration`.

When startup fails on a configuration error, `blueprint-troubleshooting` carries the symptom table.
