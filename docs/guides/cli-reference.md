# CLI Reference

The `asbs` command-line tool is the primary interface for scaffolding, developing, and managing Blueprint Agents projects. It is installed automatically with the `avs-blueprint-agents` package.

```bash
pip install avs-blueprint-agents
```

---

## Naming Conventions and Auto-Registration

All `asbs create` commands follow consistent naming conventions and automatically register components in `src/main.py`.

### Input Flexibility

The CLI accepts component names in multiple formats and normalizes them to proper class and file names:

- **snake_case**: `order_placed` → `OrderPlacedHandler`
- **CamelCase**: `OrderPlaced` → `OrderPlacedHandler`
- **kebab-case**: `order-placed` → `OrderPlacedHandler`

All formats are converted to proper class names without double suffixes (e.g., never `OrderPlacedHandlerHandler`).

### Component Naming

Each component type follows a consistent suffix pattern:

| Component Type | Input | Class Name | File Name | Notes |
|---|---|---|---|---|
| **Handler** | `order_placed` | `OrderPlacedHandler` | `order_placed_handler.py` | Handles events |
| **Service** | `invoice_processor` | `InvoiceProcessorService` | `invoice_processor_service.py` | Contains business logic |
| **API** | `order_management` | `OrderManagementApi` | `order_management_api.py` | REST endpoints + models file |
| **Agent** | `document_analyzer` | `DocumentAnalyzer` | `document_analyzer_agent.py` | No "Agent" suffix in class name |
| **Scheduler** | `cleanup` | `CleanupScheduler` | `cleanup_scheduler.py` | Background tasks |

### Name Normalization Examples

The CLI handles various input formats correctly:

#### Handler Examples
```bash
asbs create handler order_placed     # Snake case input
asbs create handler OrderPlaced      # CamelCase input
asbs create handler order-placed     # Kebab-case input
# All produce: OrderPlacedHandler in order_placed_handler.py
```

#### Service Examples
```bash
asbs create service user_manager
asbs create service UserManager
asbs create service user-manager
# All produce: UserManagerService in user_manager_service.py
```

#### API Examples
```bash
asbs create api product_catalog
asbs create api ProductCatalog
asbs create api product-catalog
# All produce: ProductCatalogApi in product_catalog_api.py
# And: product_catalog_models.py (without the "_api" suffix)
```

#### Agent Examples
```bash
asbs create agent document_analyzer
asbs create agent DocumentAnalyzer
asbs create agent document-analyzer
# All produce: DocumentAnalyzer (agent class, not DocumentAnalyzerAgent)
# File: document_analyzer_agent.py
# Builder function: build_document_analyzer_agent()
```

### Auto-Registration

When you create a component, the CLI automatically:

1. **Creates the component file** in the appropriate directory
2. **Adds imports** to `src/main.py`
3. **Registers with AppBuilder** in the chain

If auto-registration fails (e.g., `src/main.py` not found), the CLI displays a clear error message with manual registration instructions.

#### Example Auto-Registration Output

```bash
$ asbs create handler order_placed
✓ Created handler: src/handlers/order_placed_handler.py
✓ Auto-registered in src/main.py
  - Added import: from src.handlers.order_placed_handler import OrderPlacedHandler
  - Added registration: .with_handler(OrderPlacedHandler)
```

---

## asbs setup

Scaffold a complete Blueprint Agents project with all required directories and configuration files.

```bash
asbs setup <project-name>
```

### Arguments

| Argument       | Description                        | Required |
|----------------|------------------------------------|----------|
| `project-name` | Name of the project to create      | Yes      |

### Generated Project Structure

```
<project-name>/
  src/
    main.py
    handlers/
    services/
    api/
    models/
    prompts/
  tests/
    unit/
    integration/
  settings.toml
  secrets.toml
  pyproject.toml
  Dockerfile
```

### Example

```bash
asbs setup my-ai-service
```

The generated `main.py` is a **declaration**, not an application. Nothing is constructed until
something calls `build()`, which is what lets the same file be served on its own and be hosted
alongside other agents in one process:

```python
from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder

from .services import MyAiServiceService

my_ai_service_agent = (
    AgentBuilder(runtime_name="my_ai_service_agent")
    .with_model_from_config()
    .with_system_prompt("my_ai_service_agent_system")
)

agent = (
    AppBuilder()
    .with_service(MyAiServiceService)
    .with_agent(my_ai_service_agent, name="my_ai_service_agent")
)
```

Components are registered as **classes**, not instances: a component constructed on the `with_*`
line is constructed before any namespace exists and belongs to the root for ever, which is why a
group refuses one.

`asbs setup` also writes `agents.toml`, which maps the agent's name to that declaration:

```toml
[agents.my_ai_service]
module = "src.main:agent"
```

That name is the agent's identity everywhere outside the file -- the NATS queue group, part of the
JetStream durable name, the cache partition, the OpenTelemetry `service.name` and the `/api/<name>`
route prefix -- so changing it after the first deploy is a consumer migration. The project is run
with `python -m blueprint.agents.entrypoint`, which reads that map and the deployment's group.

---

## asbs create handler

Generate a new event handler component by creating a subclass of `EventHandlerBase`.

```bash
asbs create handler <name> [--event-type <type>] [--priority <int>]
```

### Arguments

| Argument | Description                     | Required |
|----------|---------------------------------|----------|
| `name`   | Name of the handler to create   | Yes      |

### Options

| Flag                    | Description                                        | Default   |
|-------------------------|----------------------------------------------------|-----------|
| `--event-type <type>`   | The event type this handler will respond to         | (prompt)  |
| `--priority <int>`      | Handler priority (lower numbers execute first)      | `0`       |

### Naming

Handler names are converted to `<Name>Handler` format:

- Input: `order_placed` → Class: `OrderPlacedHandler` → File: `order_placed_handler.py`
- Input: `OrderPlaced` → Class: `OrderPlacedHandler` → File: `order_placed_handler.py`
- Input: `order-placed` → Class: `OrderPlacedHandler` → File: `order_placed_handler.py`

### Auto-Registration

The created handler is automatically:
- Imported in `src/main.py`
- Registered with `.with_handler(OrderPlacedHandler)`

If auto-registration fails, manual registration instructions are provided.

### Examples

#### Basic Handler

```bash
asbs create handler order_placed --event-type "order.placed"
```

Creates `src/handlers/order_placed_handler.py` with an `OrderPlacedHandler` class.

#### Handler with Priority

```bash
asbs create handler high_priority_event --event-type "system.alert" --priority 5
```

Handlers with lower priority numbers execute first in the chain.

#### Handler Generated Code

The generated handler includes:

```python
from blueprint.agents.handler import EventHandlerBase

class OrderPlacedHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=0)

    async def on_startup(self) -> None:
        # Initialize resources from registry
        pass

    async def on_shutdown(self) -> None:
        # Clean up resources
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "order.placed"

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult | None:
        # Return None to pass to next handler
        # Return HandlerResult(...) to publish and stop chain
        return None
```

---

## asbs create service

Generate a new service component by creating a subclass of `ServiceBase`.

```bash
asbs create service <name>
```

### Arguments

| Argument | Description                     | Required |
|----------|---------------------------------|----------|
| `name`   | Name of the service to create   | Yes      |

### Naming

Service names are converted to `<Name>Service` format:

- Input: `invoice_processor` → Class: `InvoiceProcessorService` → File: `invoice_processor_service.py`
- Input: `InvoiceProcessor` → Class: `InvoiceProcessorService` → File: `invoice_processor_service.py`
- Input: `invoice-processor` → Class: `InvoiceProcessorService` → File: `invoice_processor_service.py`

### Auto-Registration

The created service is automatically:
- Imported in `src/main.py`
- Registered with `.with_service(InvoiceProcessorService)`

### Examples

#### Basic Service

```bash
asbs create service invoice_processor
```

Creates `src/services/invoice_processor_service.py` with an `InvoiceProcessorService` class.

#### Service Generated Code

The generated service includes:

```python
from blueprint.agents.services import ServiceBase

class InvoiceProcessorService(ServiceBase):
    async def on_startup(self) -> None:
        # Initialize resources, fetch dependencies from registry
        # Example: self._cache = self.registry.cache_service
        # Example: self._agent = self.registry.get_agent("analyzer")
        pass

    async def on_shutdown(self) -> None:
        # Clean up resources
        pass

    async def process(self, data: dict) -> dict:
        """Process invoice data.

        Args:
            data: Invoice information

        Returns:
            Processing result
        """
        # TODO: Implement business logic
        pass
```

---

## asbs create api

Generate a new REST API component by creating a subclass of `RestApiBase`, plus a models file with Request/Response classes.

```bash
asbs create api <name>
```

### Arguments

| Argument | Description                  | Required |
|----------|------------------------------|----------|
| `name`   | Name of the API to create    | Yes      |

### Naming

API names are converted to `<Name>Api` format with an accompanying models file:

- Input: `order_management`
  - Class: `OrderManagementApi`
  - API File: `order_management_api.py`
  - Models File: `order_management_models.py`

### Files Generated

1. **API File** (`src/api/<name>_api.py`)
   - REST API class with `.get()`, `.post()`, `.put()`, `.delete()` endpoints
   - Dependency injection via `self.registry.get_service(...)`

2. **Models File** (`src/models/<name>_models.py`)
   - Request and Response Pydantic models
   - Example: `OrderManagementRequest` and `OrderManagementResponse`

### Auto-Registration

The created API is automatically:
- Imported in `src/main.py` (both models and API)
- Registered with `.with_rest_api(OrderManagementApi)`

### Examples

#### Basic API

```bash
asbs create api order_management
```

Creates:
- `src/api/order_management_api.py` with `OrderManagementApi` class
- `src/models/order_management_models.py` with `OrderManagementRequest` and `OrderManagementResponse` classes

#### API Generated Code

The generated API includes:

```python
"""REST API for order_management operations."""

from fastapi import HTTPException, status
from blueprint.agents.io.api.rest_api_base import RestApiBase
from src.models.order_management_models import OrderManagementRequest, OrderManagementResponse

class OrderManagementApi(RestApiBase):
    async def on_startup(self) -> None:
        # Initialize dependencies from registry
        # Example: self._service = self.registry.get_service(OrderService)
        pass

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/{item_id}", response_model=OrderManagementResponse)
    async def get_item(self, item_id: str) -> OrderManagementResponse:
        """Get item by ID."""
        # TODO: Implement get logic
        pass

    @RestApiBase.post("/", response_model=OrderManagementResponse)
    async def create_item(self, request: OrderManagementRequest) -> OrderManagementResponse:
        """Create new item."""
        # TODO: Implement create logic
        pass
```

The accompanying models file includes:

```python
from pydantic import BaseModel

class OrderManagementRequest(BaseModel):
    """Request model for order_management operations."""
    # TODO: Add your request fields
    pass

class OrderManagementResponse(BaseModel):
    """Response model for order_management operations."""
    # TODO: Add your response fields
    pass
```

---

## asbs create agent

Generate an AI agent component with `AgentRuntime`, `AgentBuilder` boilerplate, system prompt, instruction prompt, and settings configuration.

```bash
asbs create agent <name>
```

### Arguments

| Argument | Description                    | Required |
|----------|--------------------------------|----------|
| `name`   | Name of the agent to create    | Yes      |

### Naming

Agent names are converted to `<Name>` format (no "Agent" suffix in class name, but used in builder function):

- Input: `document_analyzer` → Function: `build_document_analyzer_agent()` → File: `document_analyzer_agent.py`
- Input: `DocumentAnalyzer` → Function: `build_document_analyzer_agent()` → File: `document_analyzer_agent.py`

### Files Generated

1. **Agent Module** (`src/agents/<name>_agent.py`)
   - `build_<name>_agent(config)` function that creates and configures the agent
   - Uses `AgentBuilder` with model config, prompts, and tools

2. **System Prompt** (`src/prompts/<name>_system.prompt`)
   - Static context for the agent
   - Example content already provided

3. **Instruction Prompt** (`src/prompts/<name>_instruction.prompt`)
   - Dynamic template with `{placeholders}` for runtime input
   - Example content already provided

4. **Settings Configuration** (`settings.toml`)
   - `[default.runtimes.<name>]` section with model configuration
   - Model provider, name, temperature, and token limits

### Auto-Registration

The created agent is automatically:
- Imported in `src/main.py`
- Agent instance created before `app =`
- Registered with `.with_agent(<name>_agent, name="<name>_agent")`
- Configuration added to `settings.toml`

### Examples

#### Basic Agent

```bash
asbs create agent document_analyzer
```

Creates:
- `src/agents/document_analyzer_agent.py` with `build_document_analyzer_agent()` function
- `src/prompts/document_analyzer_system.prompt` with system context
- `src/prompts/document_analyzer_instruction.prompt` with instruction template
- `[default.runtimes.document_analyzer]` section in `settings.toml`

#### Agent Generated Code

The generated agent builder includes:

```python
"""AgentRuntime for document_analyzer operations."""

from blueprint.agents import AgentBuilder
from blueprint.agents.base import AgentRuntime
from blueprint.agents.config import Config


def build_document_analyzer_agent(config: Config) -> AgentRuntime:
    """Build the document_analyzer agent.

    Args:
        config: Application configuration

    Returns:
        Configured AgentRuntime instance
    """
    agent = (
        AgentBuilder(config, runtime_name="document_analyzer")
        .with_model_from_config()
        .with_system_prompt("document_analyzer_system")
        .build(name="document_analyzer")
    )

    return agent
```

#### Settings Configuration

Auto-generated in `settings.toml`:

```toml
[default.runtimes.document_analyzer]
model_provider = "openai"
model_name = "gpt-4o-mini"
model_temperature = 0.7
model_max_tokens = 2000
```

Override any defaults in your `settings.toml` after creation.

---

## asbs create scheduler

Generate a scheduled task component by creating a subclass of `SchedulerBase`.

```bash
asbs create scheduler <name> [--cron <expr>]
```

### Arguments

| Argument | Description                        | Required |
|----------|------------------------------------|----------|
| `name`   | Name of the scheduler to create    | Yes      |

### Options

| Flag             | Description                          | Default       |
|------------------|--------------------------------------|---------------|
| `--cron <expr>`  | Cron expression for the schedule     | `0 * * * *`   |

### Naming

Scheduler names are converted to `<Name>Scheduler` format:

- Input: `cleanup` → Class: `CleanupScheduler` → File: `cleanup_scheduler.py`
- Input: `Cleanup` → Class: `CleanupScheduler` → File: `cleanup_scheduler.py`
- Input: `cleanup-task` → Class: `CleanupTaskScheduler` → File: `cleanup_task_scheduler.py`

### Auto-Registration

The created scheduler is automatically:
- Imported in `src/main.py`
- Registered with `.with_scheduler(CleanupScheduler)`

### Cron Expressions

Use standard 5-field cron syntax:

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-7, 0=Sunday)
│ │ │ │ │
│ │ │ │ │
* * * * *
```

Common patterns:
- `*/5 * * * *` - Every 5 minutes
- `0 * * * *` - Every hour at minute 0
- `0 2 * * *` - Daily at 2:00 AM
- `0 8 * * 1-5` - Weekdays at 8:00 AM
- `0 0 1 * *` - Monthly at midnight on the 1st

### Examples

#### Hourly Scheduler

```bash
asbs create scheduler metrics_collector
```

Creates `src/schedulers/metrics_collector_scheduler.py` with default hourly schedule.

#### Custom Cron Schedule

```bash
asbs create scheduler daily_cleanup --cron "0 2 * * *"
```

Creates a scheduler that runs daily at 2:00 AM.

#### Scheduler Generated Code

The generated scheduler includes:

```python
"""Scheduler for cleanup operations."""

import logging
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase

logger = logging.getLogger(__name__)


class CleanupScheduler(SchedulerBase):
    """Scheduler for cleanup operations."""

    def __init__(self) -> None:
        """Initialize the scheduler."""
        super().__init__(crontab="0 2 * * *")

    async def on_startup(self) -> None:
        """Initialize the scheduler."""
        # TODO: Get services from registry
        # Example: self._service = self.registry.get_service(CleanupService)

    async def on_shutdown(self) -> None:
        """Cleanup when shutting down."""

    async def tick(self) -> None:
        """Execute scheduled task."""
        try:
            # TODO: Implement your scheduled task here
            # Example: await self._service.cleanup()
        except Exception as e:
            logger.exception("Error during %s scheduler tick: %s", __name__, e)
            raise
```

---

## asbs validate

Validate the project structure and configuration. Reads files only -- it never imports the
project -- and reports what it finds in three grades: **issues** (the project will not start, exit
status 1), **warnings** (it will start, and something is missing) and **notices** (a decision the
framework must not make for you).

```bash
asbs validate [<project-dir>]
```

### Checks Performed

Project shape:

- Required directories (`src/`, `tests/`) and files (`settings.toml`, `pyproject.toml`) exist
- `src/main.py` exists and uses `AppBuilder`
- `secrets.toml.example` and `secrets.toml` are present
- A `Dockerfile` is present

Group readiness -- what this project must state before it can be hosted beside another agent:

- `agents.toml` exists; without it the project cannot be run by
  `python -m blueprint.agents.entrypoint`, and the three changes that make it hostable are named
- Every `[agents.<name>]` entry has a `module` written as `"package.module:attribute"`
- Every agent name is a legal namespace (`[a-z][a-z0-9_]*` -- no dashes), because it becomes the
  queue group, the durable, the cache partition and the telemetry `service.name`
- Every declared module exists in the project and assigns the attribute the map names
- Once there is more than one agent: each ships its own `settings.toml` beside its declaration,
  and declares no process-scope key (`app_port`, `event_bus`, `envvar_prefix`, ...) there, since
  one process binds one port and speaks one bus

Schedulers:

- `scheduler_mode` is set when `src/schedulers/` holds anything, and is one of `in_process` or
  `event` -- it has no default, and `build()` fails without it
- In `event` mode, `event_bus` is set; and a notice that **nothing in this project generates the
  `CronJob`** that must publish the tick. A scheduler waiting for a tick nobody publishes reports
  itself healthy and never runs, which nothing else reports
- In `in_process` mode, a notice when `src/main.py` declares no cache: each tick is claimed in the
  agent's own cache so that one replica runs it, and with no cache every replica runs every tick

Delivery:

- A notice when handlers exist and `idempotency_enabled` is not declared either way. Delivery is
  at-least-once, so the decision is the author's to make and the framework will not make it

### Example

```bash
asbs validate
```

```
Validating Blueprint Agents project: /work/my-ai-service

[ok] Found agents.toml (1 agent(s): my_ai_service)

============================================================

Notices (1):
  - 'scheduler_mode' is 'event', so no timer runs in this process: each tick
    arrives as an event on '<agent>.scheduler.<scheduler name>', published by an external
    CronJob. ...
```

---

## asbs dev

Run this project's agents in development mode with hot reload, **under the namespaces they are
deployed under**. A development server at the root namespace would serve `/api/orders/{id}` where
production serves `/api/order/orders/{id}`, and would consume under a different queue group, so
every local URL and every local integration test would differ from the deployed one.

With an `agents.toml`, it serves the group through
`uvicorn blueprint.agents.entrypoint:create_group_app --factory --reload`. Without one -- a project
written before the agent map, which builds its own application -- it serves `src.main:app` exactly
as it always did.

```bash
asbs dev [--agents <a,b>] [--host <host>] [--port <port>]
```

### Options

| Flag               | Description                                                 | Default          |
|--------------------|-------------------------------------------------------------|------------------|
| `--agents <a,b>`   | Comma-separated agents to host                              | every agent in `agents.toml` |
| `--host <host>`    | Host to bind the server to                                  | `127.0.0.1`      |
| `--port <port>`    | Port to bind the server to                                  | `8000`           |

`BLUEPRINT_GROUP` or `BLUEPRINT_AGENTS` already set in the environment always wins: a developer
reproducing a particular deployment is not overridden by a default read out of the agent map.

### Example

```bash
asbs dev --port 9000
```

```
INFO:     Blueprint Agents dev server starting...
INFO:     Uvicorn running on http://0.0.0.0:9000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

The development server watches for file changes in the `src/` directory and automatically restarts when modifications are detected.

---

## Auto-Registration Troubleshooting

When `asbs create` commands run, they attempt to automatically register components in `src/main.py`. If this fails, the CLI provides clear guidance on manual registration.

### Common Issues

#### `src/main.py` Not Found

**Error:**
```
⚠ Could not auto-register (src/main.py not found or invalid)
```

**Solution:**
Ensure your project has the correct structure:
```
my_service/
├── src/
│   └── main.py
└── pyproject.toml
```

Run `asbs setup <project-name>` to scaffold a complete project if needed.

#### Invalid main.py Structure

**Error:**
```
⚠ Could not auto-register (src/main.py not found or invalid)
```

**Solution:**
Verify `src/main.py` contains:
- Import statements at the top
- An assignment whose right-hand side opens a parenthesis, with `AppBuilder(` on the next line
- A closing `)` in the first column -- or, in a project that still builds its own application, a
  `.build()` call

That is what the CLI looks for when it rewrites the chain: it is a line-oriented editor for a file
the generator wrote in a known shape, not a parser, and it reports a file it cannot read rather
than guessing at one.

Example valid structure:
```python
from blueprint.agents.app_builder import AppBuilder

agent = (
    AppBuilder()
    # Components added here
)
```

### Manual Registration

If auto-registration fails, the CLI displays instructions. Follow this pattern for each component type:

Every registration is the **class**, not an instance of it, and the declaration ends without a
`build()` call -- the host builds it.

#### Handler
```python
# In src/main.py

from .handlers import OrderPlacedHandler

agent = (
    AppBuilder()
    .with_handler(OrderPlacedHandler)
)
```

#### Service
```python
# In src/main.py

from .services import InvoiceProcessorService

agent = (
    AppBuilder()
    .with_service(InvoiceProcessorService)
)
```

#### API
```python
# In src/main.py

from .api import OrderManagementApi

agent = (
    AppBuilder()
    .with_rest_api(OrderManagementApi)
)
```

#### Agent
```python
# In src/main.py

from blueprint.agents.agent import AgentBuilder

document_analyzer_agent = (
    AgentBuilder(runtime_name="document_analyzer_agent")
    .with_model_from_config()
    .with_system_prompt("document_analyzer_agent_system")
)

agent = (
    AppBuilder()
    .with_agent(document_analyzer_agent, name="document_analyzer_agent")
)
```

The `AgentBuilder` is left **unbuilt**. `AppBuilder.build()` calls
`agent.build(config.for_namespace(<this agent>))`, so the model, prompt and metrics come from this
agent's own configuration view; building it here would bind it to whatever configuration happened
to be in scope at that line, which in a group is a neighbour's. The `name=` is the registry key
services resolve the runtime by.

#### Scheduler
```python
# In src/main.py

from .schedulers import CleanupScheduler

agent = (
    AppBuilder()
    .with_scheduler(CleanupScheduler)
)
```

### Registration Order Matters

Register dependencies **before** dependents in the AppBuilder chain:

1. Services first (contain business logic)
2. Handlers and APIs next (use services)
3. Agents last (may use multiple services)
4. Schedulers last (use services)

```python
agent = (
    AppBuilder()
    # 1. Services
    .with_service(OrderService)
    .with_service(PaymentService)
    # 2. Handlers and APIs
    .with_handler(OrderPlacedHandler)
    .with_rest_api(OrderApi)
    # 3. Agents
    .with_agent(analyzer_agent, name="analyzer_agent")
    # 4. Schedulers
    .with_scheduler(CleanupScheduler)
)
```

---

## asbs claude

Generate or update Claude Code context files for AI integration. The CLI creates framework and project-specific CLAUDE.md files automatically.

```bash
asbs claude [create|update]
```

### Subcommands

| Subcommand | Description                                              |
|------------|----------------------------------------------------------|
| `create`   | Generate new Claude Code context files                   |
| `update`   | Update existing Claude Code context files                |

### CLAUDE.md Placement

The CLI creates and manages files in a consistent structure:

| Path | Purpose | Updated By |
|------|---------|-----------|
| `src/CLAUDE.md` | Framework reference for Blueprint patterns | `asbs claude` |
| `.claude/agents/` | CLI-generated agent documentation | `asbs create agent` |
| `.claude/skills/` | CLI-generated skill definitions | `asbs` commands |
| `CLAUDE.md` (optional) | Project-specific context (root) | User (manual) |

### Framework CLAUDE.md

Running `asbs claude create` generates:

1. **`src/CLAUDE.md`** - Framework documentation containing:
   - Component base classes and imports
   - Critical rules (registry, lifecycle, wiring)
   - Component patterns with examples
   - Registry lookup patterns
   - Configuration structure
   - CLI command reference

2. **`.claude/` directory** - Generated context for Claude Code:
   - Agent documentation in `.claude/agents/`
   - Skill definitions in `.claude/skills/`
   - Automatically updated when components are created

### Example

```bash
# Generate initial Claude Code context files
asbs claude create

# Update after adding new components
asbs claude update
```

The generated files include information about:

- Project structure and component locations
- Registered handlers, services, APIs, and agents
- Configuration settings and environment variables
- Testing patterns and commands
- Build and deployment instructions

### Project-Specific CLAUDE.md

You can optionally create a `CLAUDE.md` file in your project root for project-specific context:

```markdown
# My Service - Blueprint Agents Project

## Overview
Brief description of this service's purpose and architecture.

## Key Components
- **OrderService**: Validates and processes orders
- **OrderHandler**: Responds to order.placed events
- **OrderApi**: REST endpoints for order management

## Deployment
Information specific to how this service is deployed.

## Team Guidelines
Any team-specific development guidelines or patterns.
```

This user-created file is not updated by `asbs` commands.
