# Getting Started with Blueprint Agents

This guide walks you through installing Blueprint Agents, scaffolding your first project, and running a development server.

---

## Prerequisites

- **Python 3.13+** -- Verify with `python --version`
- **pip** or **uv** -- Either package manager works; examples below show both

---

## Installation

### Option 1: Install from PyPI (stable releases)

```bash
pip install avs-blueprint-agents
```

Or with uv:

```bash
uv add avs-blueprint-agents
```

### Option 2: Install from TestPyPI (alpha releases)

For pre-release versions, configure a supplemental index in your `pyproject.toml`:

```toml
[[tool.uv.index]]
name = "test-pypi"
url = "https://test.pypi.org/simple/"
priority = "supplemental"
```

Then install as usual:

```bash
uv add avs-blueprint-agents
```

uv will fall back to the TestPyPI index when a version is not found on the primary index.

### Option 3: Install from source

```bash
git clone https://github.com/your-org/AVS.AI.Blueprint.AgenticService.git
cd AVS.AI.Blueprint.AgenticService
pip install -e ".[dev]"
```

This installs the package in editable mode with development dependencies (testing, linting, type checking).

### Verify the installation

```bash
asbs --version
```

---

## Create Your First Project

Use the `asbs` CLI to scaffold a new agent project:

```bash
asbs setup my-first-agent
```

This generates the following project structure:

```
my-first-agent/
├── src/
│   ├── __init__.py
│   ├── main.py              # AppBuilder wiring
│   ├── handlers/            # Event handlers
│   ├── services/            # Business logic
│   ├── api/                 # REST endpoints
│   ├── models/              # Pydantic models
│   └── prompts/             # LLM prompt files
├── tests/
├── settings.toml            # Configuration
├── secrets.toml             # Secrets (gitignored)
├── pyproject.toml
└── Dockerfile
```

| Directory / File | Purpose |
|------------------|---------|
| `src/main.py` | Entry point. Assembles all components using the `AppBuilder` fluent API. |
| `src/handlers/` | Event handler classes that process incoming messages and events. |
| `src/services/` | Service classes containing your core business logic. |
| `src/api/` | REST API endpoint classes exposed via FastAPI. |
| `src/models/` | Pydantic models for request/response schemas and domain objects. |
| `src/prompts/` | Prompt template files used by LLM-powered agents. |
| `settings.toml` | Application configuration managed by Dynaconf. |
| `secrets.toml` | Sensitive values (API keys, connection strings). Gitignored by default. |

---

## Run the Development Server

Start the development server with:

```bash
asbs dev
```

This will:

1. Load configuration from `settings.toml` and `secrets.toml`
2. Register all handlers, services, and API endpoints
3. Start the FastAPI server with hot-reload enabled

Once running, open your browser to view the interactive API documentation:

```
http://localhost:8000/docs
```

---

## Add Components

The `asbs create` command generates boilerplate for new components:

```bash
# Create a new event handler
asbs create handler

# Create a new service
asbs create service

# Create a new REST API endpoint
asbs create api

# Create a new scheduler
asbs create scheduler
```

Each command scaffolds a new file in the appropriate directory with the correct base class, imports, and method stubs.

---

## Understanding main.py

The `main.py` file is where you wire all components together using the `AppBuilder` fluent API. Here is a typical example:

```python
from blueprint.agents import AppBuilder, AgentBuilder, AgentRuntime, Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase

from src.handlers.my_handler import MyHandler
from src.services.my_service import MyService
from src.api.my_api import MyApi

app = (
    AppBuilder()
    .with_config(Config())
    .with_handler(MyHandler)
    .with_service(MyService)
    .with_api(MyApi)
    .with_agent(
        AgentBuilder()
        .with_name("my-agent")
        .with_prompt_file("src/prompts/system.md")
        .build()
    )
    .build()
)
```

### Key points

- **`AppBuilder`** is the central assembly point. It uses a fluent (method-chaining) API to register each component.
- **`Config`** loads values from `settings.toml` and `secrets.toml` via Dynaconf. Environment variables can override any setting.
- **Handlers** (`EventHandlerBase` subclasses) process incoming events from message queues or other sources.
- **Services** (`ServiceBase` subclasses) encapsulate reusable business logic and are injected into handlers and APIs.
- **APIs** (`RestApiBase` subclasses) define REST endpoints that are automatically mounted on the FastAPI server.
- **Agents** are configured with `AgentBuilder`, which accepts a name, prompt files, and other LLM-specific settings.
- **`AgentRuntime`** manages the lifecycle of all registered components at runtime.

---

## Configuration Basics

Blueprint Agents uses [Dynaconf](https://www.dynaconf.com/) for configuration. The two primary files are:

**settings.toml** -- General application configuration:

```toml
[default]
app_name = "my-first-agent"
log_level = "INFO"
server_port = 8000
```

**secrets.toml** -- Sensitive values (API keys, credentials):

```toml
[default]
openai_api_key = "sk-..."
database_url = "postgresql://..."
```

Environment variables override file-based settings. For example, `DYNACONF_SERVER_PORT=9000` overrides the `server_port` value.

---

## Next Steps

Now that your project is running, explore the component guides to build out your agent:

- [Event Handlers](components/event-handlers.md) -- Process events and route messages
- [Services](components/services.md) -- Write business logic with dependency injection
- [REST APIs](components/rest-apis.md) -- Expose HTTP endpoints
- [Agents](components/agents.md) -- Configure LLM-powered agents
- [Schedulers](components/schedulers.md) -- Automate recurring tasks
- [CLI Reference](guides/cli-reference.md) -- Full `asbs` command reference
- [Configuration](concepts/configuration.md) -- Deep dive into Dynaconf settings
- [Testing](guides/testing.md) -- Write tests for your components
