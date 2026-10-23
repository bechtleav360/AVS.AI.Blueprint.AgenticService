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
├── .secrets.toml           # Secrets (gitignored)
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
| `.secrets.toml` | Sensitive values (API keys, connection strings). Gitignored by default. |

---

## Run the Development Server

Start the development server with:

```bash
asbs dev
```

This will:

1. Load configuration from `settings.toml` and `.secrets.toml`
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

`src/main.py` is a **declaration**: it records what the agent is made of with the `AppBuilder`
fluent API, and nothing is constructed until the host calls `build()`. This is what `asbs setup`
writes:

```python
from pathlib import Path

from blueprint.agents import AgentBuilder, AppBuilder, Config

from .api.my_api import MyApi
from .handlers.my_handler import MyHandler
from .services.my_service import MyService

my_agent = (
    AgentBuilder(runtime_name="my_agent")
    .with_model_from_config()
    .with_system_prompt("my_agent_system")
)

agent = (
    AppBuilder()
    .with_service(MyService)
    .with_agent(my_agent, name="my_agent")
    .with_handler(MyHandler)
    .with_rest_api(MyApi)
)


def create_app():
    """Build this agent as an application of its own."""
    return agent.build(Config(settings_files=["settings.toml", ".secrets.toml"], root_path=str(Path(__file__).parent.parent)))
```

### Key points

- **`AppBuilder`** is the central assembly point. Every `with_*` call records a component, passed as
  a **class**; `build()` constructs them in dependency order and returns the FastAPI app.
- **`create_app()`** is how the agent runs on its own (`uvicorn src.main:create_app --factory`). In a
  group, `python -m blueprint.agents.entrypoint` builds the same declaration under the agent's
  namespace -- nothing in this file changes.
- **`Config`** loads values from `settings.toml` and `.secrets.toml` via Dynaconf. Environment variables can override any setting.
- **Handlers** (`EventHandlerBase` subclasses) translate incoming events into one service call each.
- **Services** (`ServiceBase` subclasses) hold all business logic and are resolved by handlers and APIs.
- **APIs** (`RestApiBase` subclasses) define REST endpoints that are automatically mounted on the FastAPI server.
- **Agents** are declared with `AgentBuilder` (unbuilt) and registered with `with_agent(builder, name=...)`; services resolve them by that name.

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

**.secrets.toml** -- Sensitive values (API keys, credentials):

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
