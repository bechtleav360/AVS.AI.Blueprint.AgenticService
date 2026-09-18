---
name: blueprint-troubleshooting
description: Diagnosing a failing Blueprint Agents service - startup errors, configuration errors, event bus connectivity, LLM provider failures, component registration errors, health check failures, cache problems and test failures. Use whenever a Blueprint service fails to start, throws at runtime, or behaves unexpectedly.
user-invocable: true
---

# Troubleshooting

**Read the symptom table before theorising.** Most failures in this framework have a known cause and
a one-line fix:

```bash
asbs docs guides/troubleshooting --cat
```

Sections map to symptoms: Installation Issues, Configuration Errors, Event Bus Connectivity, LLM
Provider Issues, Component Registration Errors, Health Check Failures, Cache Issues, Testing Issues.

## First, run the validator

```bash
asbs validate
```

It reads files only - it never imports the project - and grades what it finds: **issues** (will not
start, exit 1), **warnings** (will start, something is missing), **notices** (a decision the
framework will not make for you). It catches most misconfiguration before a stack trace does.

## The usual suspects, in order of likelihood

| Symptom | Almost always |
|---|---|
| `AttributeError` on `self.registry` or `self.config` | Accessed in `__init__`. Resolve in `on_startup()` |
| Component not found at runtime | Registered after its dependent. Services go before handlers, agents and APIs |
| Scheduler never fires | `scheduler_mode` unset, or an overridden `on_startup` that never calls `await super().on_startup()` |
| Every replica runs every scheduled tick | `scheduler_mode = "in_process"` without `.with_cache()` |
| The same event processed twice | At-least-once delivery. Make it repeatable, or set both `idempotency_enabled` and `idempotency_ttl` |
| Handler never reached | An earlier handler in the priority chain returned a `HandlerResult` and stopped the chain |
| Events vanish after a rename | The agent namespace is part of every durable name - see `blueprint-multi-agent` |
| Cache fails at startup | The disk backend needs a writable volume; a read-only root filesystem fails immediately |

## When the docs do not cover it

Narrow it down before changing code: `asbs validate` first, then the relevant section above, then
`blueprint-config` for the exact key spelling. Only then read the framework source.
