# Blueprint Agents

[![PyPI version](https://img.shields.io/pypi/v/avs-blueprint-agents)](https://pypi.org/project/avs-blueprint-agents/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CI](https://github.com/2SpeakAI/blueprint-agents/actions/workflows/ci.yml/badge.svg)](https://github.com/2SpeakAI/blueprint-agents/actions)

**A Python framework for building production-ready AI agent microservices with event-driven architecture.**

Blueprint Agents gives you a component-based toolkit for building intelligent microservices that process events, call LLMs, expose REST APIs, and run scheduled tasks -- all wired together with a fluent builder API and backed by production-grade observability.

---

## Key Features

- **Component Architecture** -- Five composable base classes (`EventHandlerBase`, `ServiceBase`, `RestApiBase`, `AgentRuntime`, `SchedulerBase`) assembled via a fluent `AppBuilder`
- **Event-Driven Processing** -- CloudEvents v1.0 with chain-of-responsibility handlers, Dapr and NATS pub/sub support
- **LLM Integration** -- AI agents powered by [Pydantic AI](https://ai.pydantic.dev/) with structured outputs, tool calling, and multi-model support (OpenAI, vLLM)
- **Built-in Observability** -- OpenTelemetry tracing, metrics, and structured logging out of the box
- **CLI Scaffolding** -- Generate complete project structures and individual components with the `asbs` CLI
- **Deployment Ready** -- Docker, Kubernetes with Helm charts, health checks, and CI/CD patterns included

---

## Quick Start

```bash
# Install the framework
pip install avs-blueprint-agents

# Scaffold a new project
asbs setup my-agent

# Start developing
cd my-agent
pip install -e .
asbs dev
```

Your service is now running at `http://localhost:8000` with interactive API docs at `/docs`.

---

## Installation

### Stable Release (PyPI)

```bash
pip install avs-blueprint-agents
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add avs-blueprint-agents
```

### Alpha Release (TestPyPI)

To install the latest alpha version for testing, add the TestPyPI index to your `pyproject.toml`:

```toml
[[tool.uv.index]]
name = "test-pypi"
url = "https://test.pypi.org/simple/"
priority = "supplemental"
```

Then install:

```bash
uv add avs-blueprint-agents
```

Or with pip:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ avs-blueprint-agents
```

### From Source

```bash
git clone https://github.com/2SpeakAI/blueprint-agents.git
cd blueprint-agents
pip install -e ".[dev]"
```

---

## How It Works

Blueprint Agents uses five composable component types, wired together with the `AppBuilder`:

```python
from blueprint.agents import AppBuilder, AgentBuilder, Config

from src.handlers.order_handler import OrderHandler
from src.services.order_service import OrderService
from src.api.routes import OrderApi

config = Config(settings_files=["settings.toml", "secrets.toml"])

app = (
    AppBuilder(config)
    .with_handler(OrderHandler)
    .with_service(OrderService)
    .with_rest_api(OrderApi())
    .with_cache()
    .build()
)
```

### The Five Components

| Component | Base Class | Purpose |
|-----------|-----------|---------|
| **Event Handler** | `EventHandlerBase` | Process CloudEvents via chain-of-responsibility with priority ordering |
| **Service** | `ServiceBase` | Encapsulate business logic with full registry access |
| **REST API** | `RestApiBase` | Define HTTP endpoints with `@get()`, `@post()`, `@put()`, `@delete()`, `@patch()` decorators |
| **Agent** | `AgentRuntime` | Run LLM agents with structured outputs, tool calling, and prompt management |
| **Scheduler** | `SchedulerBase` | Execute cron-based background tasks with auto-registered trigger endpoints |

### Component Lifecycle

All components follow a consistent lifecycle managed by the framework:

```
__init__()     -->  Register with component registry
on_startup()   -->  Resolve dependencies, connect to external services
[running]      -->  Process events, handle requests, run tasks
on_shutdown()  -->  Clean up resources, close connections
```

---

## Examples

Explore complete, runnable examples in the [`examples/`](examples/) directory:

| Example | Description | Components Used |
|---------|-------------|-----------------|
| [**inventory_api**](examples/inventory_api/) | Product inventory CRUD REST API | RestApiBase, ServiceBase, Cache |
| [**order_event_pipeline**](examples/order_event_pipeline/) | E-commerce order processing with Dapr pub/sub | EventHandlerBase, ServiceBase, Dapr |
| [**document_summarizer**](examples/document_summarizer/) | LLM-powered document summarization with structured output | AgentRuntime, AgentBuilder, Tools |
| [**webhook_relay**](examples/webhook_relay/) | Webhook ingestion and normalization pipeline with NATS | EventHandlerBase, NATS, Cache |
| [**health_monitor**](examples/health_monitor/) | System health monitoring with scheduled checks | SchedulerBase, ServiceBase, Cache |

---

## Configuration

Blueprint Agents uses [Dynaconf](https://www.dynaconf.com/) for hierarchical configuration via TOML files:

**settings.toml** (checked into version control):

```toml
[default]
app_name = "my-agent"
app_port = 8000
event_bus = "dapr"          # "dapr", "nats", or "sessions"
log_level = "INFO"

[default.runtimes.my_agent]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_max_tokens = 1000
model_temperature = 0.3

[default.cache]
cache_dir = ".cache/my-agent"
default_ttl = 3600
```

**secrets.toml** (never commit this file):

```toml
[default.runtimes.my_agent]
model_api_key = "sk-your-api-key"
```

For the **sessions transport** (consumes SSE jobs from `service-sessions`):

```toml
[default]
event_bus = "sessions"

[default.sessions_service]
base_url = "http://sessions:8000"
agent_id = "my-agent"
agent_type = "analyser"
capabilities = ["analyse_documents"]
api_key = "@format {env[SESSIONS_API_KEY]}"
max_concurrent_jobs = 5
job_timeout_seconds = 300
```

No `SessionsBus`, `SessionsApiClient`, or `SessionKeyProvider` references in service `main.py` — `AppBuilder.build()` wires them automatically.

See the [Configuration Reference](docs/concepts/configuration.md) for all available settings.

---

## CLI Reference

The `asbs` CLI scaffolds projects and components:

```bash
asbs setup <project-name>                         # Create a new project
asbs create handler <name> [--event-type <type>]  # Add an event handler
asbs create service <name>                        # Add a business service
asbs create api <name>                            # Add a REST API
asbs create agent <name>                          # Add an AI agent
asbs create scheduler <name> [--cron <expr>]      # Add a scheduler
asbs validate                                     # Validate project structure
asbs dev [--port <port>]                          # Run development server
```

See the full [CLI Reference](docs/guides/cli-reference.md).

---

## Deployment

Blueprint Agents services deploy as standard Python containers:

- **Docker** -- Multi-stage Dockerfile included with scaffolded projects
- **Kubernetes** -- Helm charts with Dapr sidecar injection, health probes, and ConfigMap/Secret management
- **CI/CD** -- GitHub Actions workflows for linting, testing, and publishing

See the [Deployment Guide](docs/guides/deployment.md) for detailed instructions.

---

## Documentation

### Getting Started
- [Getting Started Guide](docs/getting-started.md) -- Installation, first project, and walkthrough

### Core Concepts
- [Architecture](docs/concepts/architecture.md) -- Component model, registry, and lifecycle
- [Event Processing](docs/concepts/event-processing.md) -- CloudEvents, handler chain, Dapr/NATS
- [Configuration](docs/concepts/configuration.md) -- Settings, secrets, and environment variables
- [Caching](docs/concepts/caching.md) -- Persistent disk cache with TTL and namespaces
- [Observability](docs/concepts/observability.md) -- OpenTelemetry tracing, metrics, and logging

### Component Guides
- [Event Handlers](docs/components/event-handlers.md)
- [Services](docs/components/services.md)
- [REST APIs](docs/components/rest-apis.md)
- [Agents](docs/components/agents.md)
- [Schedulers](docs/components/schedulers.md)

### Operations
- [CLI Reference](docs/guides/cli-reference.md)
- [Testing Guide](docs/guides/testing.md)
- [Deployment Guide](docs/guides/deployment.md)
- [Troubleshooting](docs/guides/troubleshooting.md)

### Reference
- [API Reference](docs/reference/api.md)
- [Configuration Keys](docs/reference/configuration-keys.md)
- [Data Models](docs/reference/models.md)

---

## Requirements

- **Python 3.13+**
- **Docker** (optional, for containerized deployment)
- **Dapr CLI** (optional, for Dapr pub/sub event processing)
- **NATS Server** (optional, for NATS event processing)
- **API keys** for AI providers (optional, only for LLM agent features)

---

## Contributing

We welcome contributions! See [CONTRIBUTE.md](CONTRIBUTE.md) for guidelines on:

- Setting up the development environment
- Running tests and linting
- Submitting pull requests

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
