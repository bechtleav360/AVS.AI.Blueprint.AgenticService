# Blueprint Agents Documentation

Blueprint Agents is a Python 3.13+ framework for building AI-powered microservices. It provides a component-based architecture assembled through a fluent `AppBuilder` API, with built-in support for event processing, REST APIs, scheduling, caching, and observability.

---

## Getting Started

| Guide | Description |
|-------|-------------|
| [Getting Started](getting-started.md) | Install the framework, scaffold a project, and run your first agent |

---

## Core Concepts

| Topic | Description |
|-------|-------------|
| [Architecture](concepts/architecture.md) | AppBuilder pattern, component lifecycle, and dependency injection |
| [Event Processing](concepts/event-processing.md) | Event handler pipeline, message routing, and processing model |
| [Configuration](concepts/configuration.md) | Dynaconf-based config with `settings.toml` and `secrets.toml` |
| [Caching](concepts/caching.md) | Built-in caching strategies and cache provider integration |
| [Observability](concepts/observability.md) | Logging, metrics, tracing, and health checks |

---

## Component Guides

| Component | Description |
|-----------|-------------|
| [Event Handlers](components/event-handlers.md) | Process incoming events by extending `EventHandlerBase` |
| [Services](components/services.md) | Encapsulate business logic by extending `ServiceBase` |
| [REST APIs](components/rest-apis.md) | Expose HTTP endpoints by extending `RestApiBase` |
| [Agents](components/agents.md) | Configure LLM-powered agents with `AgentBuilder` |
| [Schedulers](components/schedulers.md) | Run recurring tasks by extending `SchedulerBase` |

---

## Guides

| Guide | Description |
|-------|-------------|
| [CLI Reference](guides/cli-reference.md) | Full reference for the `asbs` command-line tool |
| [Testing](guides/testing.md) | Unit testing, integration testing, and test fixtures |
| [Deployment](guides/deployment.md) | Docker builds, environment configuration, and production setup |
| [Troubleshooting](guides/troubleshooting.md) | Common issues, debugging tips, and FAQ |

---

## Reference

| Reference | Description |
|-----------|-------------|
| [API Reference](reference/api.md) | Public API surface for all framework modules |
| [Configuration Keys](reference/configuration-keys.md) | Complete list of `settings.toml` and `secrets.toml` keys |
| [Models](reference/models.md) | Built-in Pydantic models and base classes |
