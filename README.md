# Blueprint Agents

[![PyPI version](https://img.shields.io/pypi/v/avs-blueprint-agents)](https://pypi.org/project/avs-blueprint-agents/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/LICENSE)
[![CI](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/actions/workflows/ci.yml/badge.svg)](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/actions)

**A Python framework for building production-ready AI agent microservices with event-driven architecture.**

Blueprint Agents gives you a component-based toolkit for building intelligent microservices that process events, call LLMs, expose REST APIs, and run scheduled tasks -- all wired together with a fluent builder API and backed by production-grade observability.

---

## Key Features

- **Component Architecture** -- Five composable base classes (`EventHandlerBase`, `ServiceBase`, `RestApiBase`, `AgentRuntime`, `SchedulerBase`) assembled via a fluent `AppBuilder`
- **Event-Driven Processing** -- CloudEvents v1.0 with chain-of-responsibility handlers, Dapr and NATS pub/sub support
- **LLM Integration** -- AI agents powered by [Pydantic AI](https://ai.pydantic.dev/) with structured outputs, tool calling, and multi-model support (OpenAI, vLLM)
- **Built-in Observability** -- OpenTelemetry tracing, metrics, and structured logging out of the box
- **Multi-Agent Grouping** -- Run one agent per process, or host several in one process, as a *deployment* choice: the agent's code is identical either way
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

Your service is now running at `http://localhost:8000` with interactive API docs at `/docs`,
and this agent's routes under `/api/my-agent`.

`asbs setup` writes your project's `main.py` as a **declaration** -- an `AppBuilder` that is never built --
plus an `agents.toml` naming it. That is what lets the same project run on its own and be hosted
alongside other agents without changing a line. See
[Running one agent, or several](#running-one-agent-or-several).

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

Alpha builds are published to TestPyPI. **TestPyPI must be used for this package only** -- it also
carries stale copies of common dependencies (an ancient `fastapi`, an `apscheduler` too old for
this package), and any setup that lets the resolver reach them for *dependencies* fails.

With uv, name the index for this one package and nothing else:

```toml
[[tool.uv.index]]
name = "test-pypi"
url = "https://test.pypi.org/simple/"
explicit = true                                    # only for packages that name it below

[tool.uv.sources]
avs-blueprint-agents = { index = "test-pypi" }
```

```bash
uv add "avs-blueprint-agents==0.9.0a1"
```

`explicit = true` is the load-bearing part: without it uv applies its default `first-index`
strategy, pins every dependency to the first index that happens to contain it, and the resolution
fails on TestPyPI's old `apscheduler`. That is deliberate protection against dependency confusion,
not something to work around with `--index-strategy unsafe-best-match`.

**pip has no equivalent** -- no index priority and no per-package source, so `--extra-index-url`
merges both indexes and the broken copies stay reachable whichever order the flags are in. Fetch
the package alone, then install it with dependencies resolved from PyPI:

```bash
pip download --no-deps --index-url https://test.pypi.org/simple/ "avs-blueprint-agents==0.9.0a1" -d ./dl
pip install --index-url https://pypi.org/simple/ ./dl/avs_blueprint_agents-0.9.0a1-py3-none-any.whl
```

Pin the exact alpha version in both cases: PyPI carries the newer stable release, and an unpinned
install resolves to that instead.

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
from blueprint.agents import AppBuilder

from src.handlers.order_handler import OrderHandler
from src.services.order_service import OrderService
from src.api.routes import OrderApi

agent = (
    AppBuilder()
    .with_handler(OrderHandler)
    .with_service(OrderService)
    .with_rest_api(OrderApi)
    .with_cache()
)
```

Two things about that chain are worth knowing up front:

- **Nothing is constructed yet.** Every `with_*` call records a declaration; `build()` constructs
  it. Leaving `build()` out is what lets the deployment decide the configuration and the namespace
  each component is built in.
- **Pass classes, not instances.** `with_rest_api(OrderApi)` rather than `with_rest_api(OrderApi())`.
  An instance created on the `with_*` line exists before any namespace does, so it belongs to the
  process root for ever. Instances still work for a single standalone agent; a group refuses them.

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

## Running one agent, or several

**How many agents share a process is a deployment parameter, not an architectural commitment.**
The declaration in your project's `main.py` is the same either way; only what starts the
process differs.

| Shape | What starts it |
|---|---|
| Standalone, a module-level `app` you built yourself | `uvicorn src.main:app` |
| Standalone, a declaration built by a factory | `uvicorn src.main:create_app --factory` |
| Hosted -- one agent, or twenty | `python -m blueprint.agents.entrypoint` |

### Standalone

Unchanged, and still fully supported. Build the declaration yourself and serve it:

```python
config = Config(settings_files=["settings.toml", ".secrets.toml"])
app = agent.build(config)          # the declaration from "How It Works"
```

A standalone agent runs at the **root namespace**: its registry names, REST paths (`/api/...`),
NATS queue group, JetStream durable and OpenTelemetry `service.name` are exactly what they were
before this existed. Nothing reads `agents.toml` unless you run the entry point.

### Hosted in a group

Name each agent and the module its declaration lives in, in `agents.toml`:

```toml
[agents.orders]
module = "src.main:agent"

[agents.billing]
module = "billing.main:agent"
```

The image contains those agents; the **deployment** decides which of them a given process runs:

```bash
docker run -e BLUEPRINT_AGENTS=orders,billing my-image      # both in one process
docker run -e BLUEPRINT_AGENTS=orders my-image              # a group of one
```

Each hosted agent gets its own handlers, agent runtime, REST routes, AI client, thread pool,
caches and broker connection. The port, the health endpoint and the process are shared. Agents in
one process are **isolated**: an agent resolves its own components, caches and configuration and
the root's shared ones, and the framework refuses any attempt to reach a neighbour's.

A group of one gives today's process isolation; a group of twenty gives the shared-interpreter
memory profile. Moving an agent between groups changes neither its broker-side consumer identity
nor its telemetry identity.

> **The agent's name in `agents.toml` is its identity everywhere else** -- registry prefix, NATS
> queue group, part of the JetStream durable, cache partition, OpenTelemetry `service.name` and
> the REST prefix `/api/<name>`. Renaming it after the first deploy is a consumer migration, not a
> rename. Choose it before you ship.

Other group settings: `BLUEPRINT_GROUP_CONFIG` and `BLUEPRINT_GROUP` select a named group from a
mounted file, and `BLUEPRINT_CRITICAL_AGENTS` says which agents failing should fail the process.
See the [Multi-Agent Setup guide](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/multi-agent-setup.md) for the full reference and the
migration path for an existing single-agent project.

---

## Examples

Explore complete, runnable examples in the [`examples/`](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/examples/) directory:

| Example | Description | Components Used |
|---------|-------------|-----------------|
| [**inventory_api**](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/examples/inventory_api/) | Product inventory CRUD REST API | RestApiBase, ServiceBase, Cache |
| [**order_event_pipeline**](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/examples/order_event_pipeline/) | E-commerce order processing with Dapr pub/sub | EventHandlerBase, ServiceBase, Dapr |
| [**document_summarizer**](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/examples/document_summarizer/) | LLM-powered document summarization with structured output | AgentRuntime, AgentBuilder, Tools |
| [**webhook_relay**](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/examples/webhook_relay/) | Webhook ingestion and normalization pipeline with NATS | EventHandlerBase, NATS, Cache |
| [**health_monitor**](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/examples/health_monitor/) | System health monitoring with scheduled checks | SchedulerBase, ServiceBase, Cache |

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

**.secrets.toml** (never commit this file):

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

See the [Configuration Reference](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/concepts/configuration.md) for all available settings.

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

See the full [CLI Reference](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/cli-reference.md).

---

## Deployment

Blueprint Agents services deploy as standard Python containers:

- **Docker** -- Multi-stage Dockerfile included with scaffolded projects
- **Kubernetes** -- Helm charts with Dapr sidecar injection, health probes, and ConfigMap/Secret management
- **CI/CD** -- GitHub Actions workflows for linting, testing, and publishing

See the [Deployment Guide](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/deployment.md) for detailed instructions.

---

## Documentation

**The documentation ships with the package.** Every page below is installed alongside the code, so
a developer -- or an AI assistant working in your project -- can read it without network access:

```bash
asbs docs                                      # list every page
asbs docs guides/multi-agent-setup             # print the path to one page
asbs docs reference/configuration-keys --cat   # print its contents
```

`asbs claude` additionally installs Claude Code skills that route to the right page for the task at
hand. The links below are the same pages on GitHub, for browsing.

### Getting Started
- [Getting Started Guide](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/getting-started.md) -- Installation, first project, and walkthrough
- [Multi-Agent Setup](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/multi-agent-setup.md) -- Running several agents in one process
- [Multi-Agent Migration](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/multi-agent-migration.md) -- Moving an existing agent into a group

### Core Concepts
- [Architecture](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/concepts/architecture.md) -- Component model, registry, and lifecycle
- [Event Processing](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/concepts/event-processing.md) -- CloudEvents, handler chain, Dapr/NATS
- [Configuration](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/concepts/configuration.md) -- Settings, secrets, and environment variables
- [Caching](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/concepts/caching.md) -- Disk and Redis caches, TTL, namespaces, and per-agent isolation
- [Observability](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/concepts/observability.md) -- OpenTelemetry tracing, metrics, and logging

### Component Guides
- [Event Handlers](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/components/event-handlers.md)
- [Services](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/components/services.md)
- [REST APIs](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/components/rest-apis.md)
- [Agents](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/components/agents.md)
- [Schedulers](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/components/schedulers.md)

### Operations
- [CLI Reference](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/cli-reference.md)
- [Testing Guide](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/testing.md)
- [Deployment Guide](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/deployment.md)
- [Troubleshooting](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/guides/troubleshooting.md)

### Reference
- [API Reference](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/reference/api.md)
- [Configuration Keys](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/reference/configuration-keys.md)
- [Data Models](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/src/blueprint/agent_generator/docs/reference/models.md)

---

## Requirements

- **Python 3.13+**
- **Docker** (optional, for containerized deployment)
- **Dapr CLI** (optional, for Dapr pub/sub event processing)
- **NATS Server** (optional, for NATS event processing)
- **API keys** for AI providers (optional, only for LLM agent features)

---

## Contributing

We welcome contributions! See [CONTRIBUTE.md](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/CONTRIBUTE.md) for guidelines on:

- Setting up the development environment
- Running tests and linting
- Submitting pull requests

---

## License

This project is licensed under the MIT License. See [LICENSE](https://github.com/bechtleav360/AVS.AI.Blueprint.AgenticService/blob/develop/LICENSE) for details.
