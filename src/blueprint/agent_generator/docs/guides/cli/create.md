# asbs create

## asbs create handler

Generate a new event handler component by creating a subclass of `EventHandlerBase`.

```bash
asbs create handler <name> [--event-type <type>] [--priority <int>] [--output-dir <dir>]
```

### Arguments

| Argument | Description                     | Required |
|----------|---------------------------------|----------|
| `name`   | Name of the handler to create   | Yes      |

### Options

| Flag                    | Description                                        | Default          |
|-------------------------|----------------------------------------------------|------------------|
| `--event-type <type>`   | The event type this handler will respond to        | (prompt)         |
| `--priority <int>`      | Handler priority (lower numbers execute first)     | `10`             |
| `--output-dir <dir>`    | Where the handler module is written                | `src/handlers`   |

Ties at equal priority are resolved by registration order, which is the order the `with_*` calls
appear in `main.py`.

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
        super().__init__(priority=10)

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
asbs create service <name> [--output-dir <dir>]
```

### Arguments

| Argument | Description                     | Required |
|----------|---------------------------------|----------|
| `name`   | Name of the service to create   | Yes      |

### Options

| Flag                  | Description                         | Default          |
|-----------------------|-------------------------------------|------------------|
| `--output-dir <dir>`  | Where the service module is written | `src/services`   |

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
asbs create api <name> [--output-dir <dir>]
```

### Arguments

| Argument | Description                  | Required |
|----------|------------------------------|----------|
| `name`   | Name of the API to create    | Yes      |

### Options

| Flag                  | Description                     | Default     |
|-----------------------|---------------------------------|-------------|
| `--output-dir <dir>`  | Where the API module is written | `src/api`   |

### Naming

API names are converted to `<Name>Api`, with a models package named after the component:

- Input: `order_management`
  - Class: `OrderManagementApi`
  - API file: `src/api/order_management_api.py`
  - Models package: `src/models/order_management/`

### Files Generated

1. **API module** (`src/api/<name>_api.py`)
   - `RestApiBase` subclass with a `GET /{item_id}` and a `POST /` placeholder, both raising
     `501 Not Implemented` until you write them
   - Dependency injection via `self.registry.get_service(...)` in `on_startup`

2. **A models package** (`src/models/<name>/`), three files:
   - `dto.py` -- `<Name>Request` and `<Name>Response`, the API's wire contract
   - `domain_models.py` -- `<Name>Model`, what the service works with
   - `mapper.py` -- `<Name>Mapper`, converting between the two

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
- `src/api/order_management_api.py` with the `OrderManagementApi` class
- `src/models/order_management/dto.py` with `OrderManagementRequest` and `OrderManagementResponse`
- `src/models/order_management/domain_models.py` with `OrderManagementModel`
- `src/models/order_management/mapper.py` with `OrderManagementMapper`

#### API Generated Code

The generated API includes:

```python
"""REST API for order_management operations."""

from fastapi import HTTPException, status
from blueprint.agents.io.api.rest_api_base import RestApiBase
from src.models.order_management.dto import OrderManagementRequest, OrderManagementResponse

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

Declare an AI agent runtime: two prompt files, a settings section, and an `AgentBuilder` in
`src/main.py`.

```bash
asbs create agent <name>
```

### Arguments

| Argument | Description                    | Required |
|----------|--------------------------------|----------|
| `name`   | Name of the agent to create    | Yes      |

### Naming

The runtime name is the input in snake case with `_agent` appended, unless it already ends that way:

- Input: `document_analyzer` -> runtime `document_analyzer_agent`
- Input: `DocumentAnalyzer` -> runtime `document_analyzer_agent`
- Input: `analyzer_agent` -> runtime `analyzer_agent`

**This command writes no module of its own.** There is no `src/agents/` file and no builder
function: an agent runtime is a declaration in `main.py` plus its prompts, so there is nothing for a
separate module to hold.

### Files Generated

1. **System prompt** (`src/prompts/<runtime>_system.prompt`) -- static context, with example content
2. **Instruction prompt** (`src/prompts/<runtime>_instruction.prompt`) -- a template with
   `{placeholders}` for runtime input, with example content
3. **Settings** (`settings.toml`) -- a `[default.runtimes.<runtime>]` section and a
   `[default.runtimes.<runtime>.models]` section beneath it

### Auto-Registration

- The `AgentBuilder` import is added to `src/main.py` if it is not already there
- The runtime declaration is inserted above the `AppBuilder` chain
- `.with_agent(<runtime>, name="<runtime>")` is added to the chain

### Examples

#### Basic Agent

```bash
asbs create agent document_analyzer
```

Creates:
- `src/prompts/document_analyzer_agent_system.prompt`
- `src/prompts/document_analyzer_agent_instruction.prompt`
- `[default.runtimes.document_analyzer_agent]` in `settings.toml`
- the declaration and the registration in `src/main.py`

#### What is added to `src/main.py`

```python
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

The builder is left **unbuilt**, and takes no `Config`. `AppBuilder.build()` calls
`agent.build(config.for_namespace(<this agent>))`, so the model, prompt and metrics are read from
this agent's own configuration view; building it at this line would bind it to whatever
configuration happened to be in scope, which in a group is a neighbour's.

#### Settings Configuration

Auto-generated in `settings.toml`:

```toml
[default.runtimes.document_analyzer_agent]
model_provider = "openai"
model_name = "gpt-5-mini"
model_temperature = 0.7
model_max_tokens = 2000

[default.runtimes.document_analyzer_agent.models]
openai_reasoning_effort = "low"
openai_reasoning_summary = "detailed"
```

Override any defaults in your `settings.toml` after creation. In a group, these are read through
this agent's own configuration view, so two agents may run different models under the same key.

---

## asbs create scheduler

Generate a scheduled task component by creating a subclass of `SchedulerBase`.

```bash
asbs create scheduler <name> [--cron <expr>] [--output-dir <dir>]
```

### Arguments

| Argument | Description                        | Required |
|----------|------------------------------------|----------|
| `name`   | Name of the scheduler to create    | Yes      |

### Options

| Flag                  | Description                             | Default            |
|-----------------------|-----------------------------------------|--------------------|
| `--cron <expr>`       | Cron expression for the schedule        | `0 * * * *`        |
| `--output-dir <dir>`  | Where the scheduler module is written   | `src/schedulers`   |

### `scheduler_mode` is required

A registered scheduler with no `scheduler_mode` in `settings.toml` fails at `build()`. The key has
no default because neither value is safe to inherit: `in_process` runs a timer in every replica and
claims each tick in the agent's own cache, so it needs `.with_cache()`; `event` starts no timer at
all and waits for a tick published by an external `CronJob`, so it needs `event_bus` -- and nothing
in this project generates that `CronJob`. `asbs validate` reports both.

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
