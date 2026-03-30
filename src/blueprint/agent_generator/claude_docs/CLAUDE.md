# Blueprint Agents Framework

Python framework for event-driven AI agent microservices. Components are wired by `AppBuilder` and share a `Registry` for dependency resolution at runtime.

## Components

| Type | Base Class | Register via | Purpose |
|------|-----------|-------------|---------|
| EventHandler | `EventHandlerBase` | `.with_handler()` | Process CloudEvents in priority chain |
| Service | `ServiceBase` | `.with_service()` | Domain logic, state, orchestration |
| AgentRuntime | via `AgentBuilder` | `.with_agent()` | LLM agent (pydantic-ai) |
| RestApi | `RestApiBase` | `.with_rest_api()` | FastAPI HTTP endpoints |
| Scheduler | `SchedulerBase` | `.with_scheduler()` | Background cron tasks |

**Imports:**

```python
from blueprint.agents import AppBuilder, Config, AgentBuilder, AgentRuntime
from blueprint.agents.handler import EventHandlerBase
from blueprint.agents.services import ServiceBase
from blueprint.agents.io.api import RestApiBase
from blueprint.agents.io.api.scheduling import SchedulerBase
from blueprint.agents.models import GenericCloudEvent, HandlerResult, CloudEvent
```

## Critical Rules

1. **NEVER access `self.registry` or `self.config` in `__init__`** — they are not linked until after construction. Always resolve dependencies in `on_startup()`.
2. **Register dependencies before dependents** — services before handlers/agents that use them.
3. **`main.py` is wiring only** — no business logic.
4. **No global state** — no module-level component instances, no singletons.
5. **All components must implement `on_startup()` and `on_shutdown()`** — even if empty.
6. **Services contain ALL business logic** — handlers and APIs are thin delegation layers.

## Wiring (main.py)

```python
from pathlib import Path
from blueprint.agents import AppBuilder, Config, AgentBuilder

config = Config(
    settings_files=["settings.toml", "secrets.toml"],
    root_path=Path(__file__).parent.parent,
)

my_agent = (
    AgentBuilder(config, runtime_name="my_agent")
    .with_model_from_config("my_agent")
    .with_system_prompt("system")
    .with_tools([...])
    .with_result_type(MyResultModel)
    .build(name="my_agent")
)

app = (
    AppBuilder(config)
    .with_service(MyService)
    .with_agent(my_agent)
    .with_handler(MyHandler)
    .with_rest_api(MyApi)
    .with_scheduler(MyScheduler)
    .with_cache()
    .build()
)
```

## Component Patterns

### EventHandler

```python
class OrderHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=10)  # Lower = runs first

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(OrderService)

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "order.placed"

    async def handle_event(
        self, event: GenericCloudEvent, context: dict[str, Any]
    ) -> HandlerResult | None:
        result = await self._service.process(event.data)
        return HandlerResult(event_type="order.processed", data=result)
```

- Return `None` → pass to next handler. Return `HandlerResult` → publish event, stop chain.

### Service

Services contain ALL business logic. Each responsibility gets its own method.

```python
class OrderService(ServiceBase):
    async def on_startup(self) -> None:
        self._agent = self.registry.get_agent("order_agent")

    async def on_shutdown(self) -> None:
        pass

    async def validate(self, order: OrderModel) -> ValidationResult:
        """Validate order against business rules."""
        ...

    async def analyze(self, order: OrderModel) -> AnalysisResult:
        """Run LLM analysis on order."""
        result = await self._agent.run(str(order.model_dump()))
        return AnalysisResult.model_validate(result.data)

    async def save(self, order: OrderModel) -> str:
        """Persist the order."""
        ...
```

### RestApi

```python
class OrderApi(RestApiBase):
    async def on_startup(self) -> None:
        self._service = self.registry.get_service(OrderService)

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.post("/orders", response_model=OrderResponse)
    async def create_order(self, payload: OrderRequest) -> OrderResponse:
        """Create a new order."""
        return await self._service.create(payload)
```

Route decorators: `@RestApiBase.get()`, `.post()`, `.put()`, `.delete()`, `.patch()`.

### Scheduler

```python
class CleanupScheduler(SchedulerBase):
    def __init__(self) -> None:
        super().__init__(crontab="0 * * * *")

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(CleanupService)

    async def on_shutdown(self) -> None:
        pass

    async def tick(self) -> None:
        """Called on each cron interval."""
        await self._service.cleanup()
```

### AgentRuntime (via AgentBuilder)

```python
agent = (
    AgentBuilder(config, runtime_name="analyzer")
    .with_model_from_config("analyzer")
    .with_system_prompt("system")              # Loads prompts/system.prompt (static, no dynamic inputs)
    .with_tools([analyze_tool])
    .with_result_type(AnalysisResult)
    .with_metrics()
    .build(name="analyzer")
)
```

**Prompt files** in `src/prompts/`:
- **System prompt** (`system.prompt`): Static context — no dynamic inputs
- **Instruction prompt** (`instruction.prompt`): Contains dynamic inputs with `{placeholders}`

## Registry Lookup

All components access others through `self.registry` (property, NOT a method):

```python
self.registry.get_service(MyService)          # By class or "my_service" string
self.registry.get_agent("my_agent")           # Agent by name
self.registry.cache_service                   # Cache (if enabled)
```

## Configuration

**settings.toml:**
```toml
[default]
app_name = "my-service"
event_bus = "dapr"
model_provider = "openai"
model_name = "gpt-4"
model_max_tokens = 2000

[default.runtimes.my_agent]     # Per-agent overrides
model_name = "gpt-4-turbo"
model_temperature = 0.5
```

**secrets.toml** (never commit): `model_api_key = "sk-..."`

## CLI (`asbs`)

```bash
asbs setup <project_name>                          # Scaffold complete project
asbs create handler <name> [--event-type TYPE]     # Add EventHandler
asbs create service <name>                         # Add Service
asbs create api <name>                             # Add RestApi
asbs create agent <name>                           # Add AgentRuntime
asbs create scheduler <name> [--cron CRON]         # Add Scheduler
asbs validate                                      # Validate project structure
asbs dev [--port 8000]                             # Run dev server
```

**IMPORTANT:** Always use `asbs create` when adding components for consistent naming and imports.

## Code Style

- Complete type hints on every method signature
- All I/O must be `async`/`await`
- `%s`-style args in log calls, not f-strings
- Pydantic validation at system boundaries
- Secrets via `secrets.toml` — never hardcoded
- Context managers (`async with`) for external resources

## Testing

- File: `test_<module>.py` | Class: `Test<Component>` | Method: `test_<behavior>_<expected>`
- `MagicMock(spec=...)` for sync, `AsyncMock()` for async deps
- Fixtures in `conftest.py` | `asyncio_mode = auto`

## Project Structure

```
src/
├── main.py          # AppBuilder wiring only
├── handlers/        # EventHandlerBase subclasses
├── services/        # ServiceBase subclasses
├── api/             # RestApiBase subclasses
├── schedulers/      # SchedulerBase subclasses
├── agents/          # AgentBuilder setup code
├── models/          # Pydantic domain models + DTOs
└── prompts/         # .prompt files (system + instruction)
```
