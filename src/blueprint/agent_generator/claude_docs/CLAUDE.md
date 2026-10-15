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
from blueprint.agents.models import GenericCloudEvent, HandlerResult, CloudEvent, create_cloud_event
```

## Critical Rules

1. **NEVER access `self.registry` or `self.config` in `__init__`** — they are not linked until after construction. Always resolve dependencies in `on_startup()`.
2. **Register dependencies before dependents** — services before handlers/agents that use them.
3. **`main.py` is wiring only** — no business logic.
4. **No global state** — no module-level component instances, no singletons.
5. **All components must implement `on_startup()` and `on_shutdown()`** — even if empty.
6. **Services contain ALL business logic** — handlers and APIs are thin delegation layers.
7. **A handler translates, it never decides.** `can_handle_event` routes on the envelope only
   (`event.type`, `event.source`, `event.subject`, the context keys) -- no I/O, no service call.
   `handle_event` is three steps: `self.extract_payload(event, Dto)` -> **one** service call ->
   translate the answer into a `HandlerResult`, `HandlerResult.skipped(reason)` or `None`.
   Calling two services in a row is already business logic: give the service one method for it.
8. **Relevance is the service's decision.** Whether *this* event needs work (a field changed, a
   status reached) is checked by the service; a handler that was routed the event but has nothing
   to do returns `HandlerResult.skipped(reason)`.
9. **Handlers never call the LLM.** No `agent.run()`, no `registry.get_agent()`, no runtime taken
   from `context` in a handler -- the service resolves its agent in `on_startup()` and runs it.
10. **No run state on `self`.** Components are shared by every concurrent run; per-event values
    live in locals and parameters. `self` holds only what `on_startup()` resolved.

## Wiring (main.py)

`src/main.py` is a **declaration**, exactly as `asbs setup` writes it: no `Config`, no `build()`,
components registered as **classes**. The host builds it -- `create_app()` when the agent runs on
its own, `python -m blueprint.agents.entrypoint` when it is one agent of a group.

```python
from pathlib import Path

from blueprint.agents import AgentBuilder, AppBuilder, Config

from .api.order_api import OrderApi
from .handlers.order_handler import OrderHandler
from .services.order_service import OrderService

order_agent = (
    AgentBuilder(runtime_name="order_agent")
    .with_model_from_config()
    .with_system_prompt("order_agent_system")
)

agent = (
    AppBuilder()
    .with_service(OrderService)
    .with_agent(order_agent, name="order_agent")
    .with_handler(OrderHandler)
    .with_rest_api(OrderApi)
)


def create_app():
    """Build this agent as an application of its own (standalone only)."""
    return agent.build(Config(settings_files=["settings.toml", ".secrets.toml"], root_path=str(Path(__file__).parent.parent)))
```

- Never build the `AgentBuilder` yourself and never pass an instance to a `with_*` call: a group
  refuses instances, because a component constructed on that line exists before any namespace does.
- Keep one registration per line in dependency order (services, agents, handlers, APIs,
  schedulers) -- `asbs create` rewrites the chain line by line.

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
        return event.type == "order.placed"  # routing on the envelope only -- no I/O

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult | None:
        payload = self.extract_payload(event, OrderPlacedEvent)  # DTO: typed, validated
        outcome = await self._service.on_order_placed(payload.order_id, event_id=event.id)  # ONE call
        if outcome is None:
            return HandlerResult.skipped("order needs no processing")
        return HandlerResult(event_type="order.processed", data=outcome.model_dump())
```

- Results: `HandlerResult` → published (if its `event_type` is mapped), chain stops.
  `HandlerResult.skipped(reason)` → this handler is responsible but the event needs nothing: chain
  stops, the delivery is acknowledged, the reason is logged at INFO, nothing is published.
  `None` → the event is offered to the next handler; if none takes it, the framework logs
  "No handler processed event".
- **Delivery is at-least-once.** The same event can reach `handle_event` more than once (lost ack, pod restart, rolling deploy). The *service* must be safe to repeat (check before you act, upsert rather than insert), or set `idempotency_enabled = true` **and** `idempotency_ttl = <seconds>` in `settings.toml` -- the framework then skips an event whose id and source it has already dispatched, within that window. Off by default on purpose: only you know whether replaying your side effects is acceptable.
- **`self.extract_payload(event, ModelType)`** — validates `event.data` against a Pydantic model and returns a typed instance. Raises `InvalidEventError` if data is missing or invalid (the framework handles this automatically).
- **The service gets no CloudEvent and no DTO.** Translate the payload into domain values (ids, domain models) in the handler; that is what lets a REST API call the same service method.
- **`context["runtime"]`** holds the agent runtime the chain bound for this handler. It is there for
  framework plumbing; a handler never runs it (rule 9) -- the service resolves its own agent.

### Service

Services contain ALL business logic, including the decision whether an event needs work at all.
Each responsibility gets its own method; the method a handler calls is the one entry point for that
event (a facade that calls the others in order).

```python
class OrderService(ServiceBase):
    async def on_startup(self) -> None:
        self._agent = self.registry.get_agent("order_agent")

    async def on_shutdown(self) -> None:
        pass

    async def on_order_placed(self, order_id: str, event_id: str) -> OrderOutcome | None:
        """Entry point for an order.placed event. None: the order needs no processing."""
        order = await self.load(order_id)
        if not self.is_relevant(order):
            return None
        await self.validate(order)
        return await self.analyze(order)

    def is_relevant(self, order: Order) -> bool:
        """Pure check, testable without mocks."""
        ...

    async def validate(self, order: OrderModel) -> ValidationResult:
        """Validate order against business rules."""
        ...

    async def analyze(self, order: OrderModel) -> AnalysisResult:
        """Run LLM analysis on order."""
        result = await self._agent.run(str(order.model_dump()))
        return AnalysisResult.model_validate(result.output)

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

**Creating CloudEvents from REST payloads** — use `create_cloud_event()` when an API endpoint needs to feed a payload into the event processing pipeline:

```python
from blueprint.agents.models import create_cloud_event

cloud_event = create_cloud_event("order.created", payload, source="/api/orders")
result = await event_processing.process_event(cloud_event)
```

`create_cloud_event()` auto-generates the event ID, auto-calls `model_dump()` on Pydantic models, and sets sensible defaults.

### Scheduler

```python
class CleanupScheduler(SchedulerBase):
    def __init__(self) -> None:
        super().__init__(crontab="0 * * * *")

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(CleanupService)
        await super().on_startup()  # required: without it the scheduler never runs

    async def on_shutdown(self) -> None:
        await super().on_shutdown()

    async def tick(self) -> None:
        """Called on each cron interval."""
        await self._service.cleanup()
```

- **Override `on_startup` only if you also call `super().on_startup()`.** The base class is
  what starts the timer, wires the tick handler and registers `POST /api/<name>/trigger`
  (`/api/<agent>/scheduler/<name>/trigger` in a group).
- **`scheduler_mode` decides what calls `tick()`, and it is required.** It has no default:
  registering a scheduler without setting it fails at startup, because neither value is safe to
  inherit silently. `"event"` starts no timer in the process -- the tick arrives as an ordinary
  event on `<app_name>.scheduler.<scheduler_name>`, published by an external `CronJob`, so the
  queue group already guarantees that exactly one replica runs it; it needs `event_bus` set to
  `"dapr"` or `"nats"`. `"in_process"` runs an APScheduler timer in **every** replica and
  claims each tick in the cache so one replica runs it -- so it needs `.with_cache()` to fire a
  tick once. Without a cache every replica runs every tick, and startup says so.
- The crontab stays declared here in both modes; it is what the `CronJob` is generated from.
- **A scheduler that wants to *publish* an event needs `event_publishing_enabled = true`.** Consuming and publishing are separate: a handler implies a transport client, a scheduler does not. The key creates the client and subscribes to nothing, and it needs `event_bus` set.

### AgentRuntime (via AgentBuilder)

```python
analyzer = (
    AgentBuilder(runtime_name="analyzer")  # declared, not built: the host builds it
    .with_model_from_config()
    .with_system_prompt("analyzer_system")  # Loads prompts/analyzer_system.prompt (static)
    .with_tools([analyze_tool])
    .with_result_type(AnalysisResult)
    .with_metrics()
)
# registered in main.py: AppBuilder()...with_agent(analyzer, name="analyzer")
```

**Prompt files** in `src/prompts/`:
- **System prompt** (`system.prompt`): Static context — no dynamic inputs. Loaded by `AgentBuilder.with_system_prompt()`.
- **Instruction prompt** (`instruction.prompt`): Contains `{placeholders}` for dynamic inputs.

**Always use `agent.get_prompt().format()` for user prompts with variable inputs:**

```python
prompt = self._agent.get_prompt("instruction").format(
    ticket_text=ticket_text,
    customer_tier=customer_tier,
)
result = await self._agent.run(user_prompt=prompt)
```

## Registry Lookup

All components access others through `self.registry` (property, NOT a method):

```python
self.registry.get_service(MyService)  # By class or "my_service" string
self.registry.get_agent("my_agent")  # Agent by name
self.registry.cache_service  # Cache (if enabled)
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

# Event deduplication -- off by default, both keys required to switch it on.
# idempotency_enabled = true
# idempotency_ttl = 1500          # seconds; must outlast the broker redelivery window

# Required once a scheduler is registered; no default. "in_process" runs a timer in
# every replica; "event" takes the tick as an event and needs event_bus set.
scheduler_mode = "in_process"

[default.runtimes.my_agent]     # Per-agent overrides
model_name = "gpt-4-turbo"
model_temperature = 0.5
```

**.secrets.toml** (never commit): `model_api_key = "sk-..."`

## Documentation

The full framework documentation ships inside the installed package -- no network needed. Locate a
page with `asbs docs`, then read it:

```bash
asbs docs                                      # list every page
asbs docs guides/multi-agent-setup             # print the path to one page
asbs docs reference/configuration-keys --cat   # print its contents
```

Prefer the matching skill (`blueprint-cli`, `blueprint-config`, `blueprint-events`,
`blueprint-multi-agent`, `blueprint-migration`, `blueprint-testing`, `blueprint-deployment`,
`blueprint-troubleshooting`); each one carries the rules that matter and points at the page for the
detail. **Never guess a configuration key or a CLI flag** -- the reference is on disk.

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
asbs docs [<topic>] [--cat]                        # Locate the framework documentation
```

**IMPORTANT:** Always use `asbs create` when adding components for consistent naming and imports.

## Code Style

- Complete type hints on every method signature
- All I/O must be `async`/`await`
- `%s`-style args in log calls, not f-strings
- Pydantic validation at system boundaries
- Secrets via `.secrets.toml` — never hardcoded
- Context managers (`async with`) for external resources
- **No `assert` statements in production code** — `assert` is only permitted in test files (`tests/`)
- **All imports at the top of the file** — never inside methods, functions, or classes

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
├── models/          # dto.py: event/REST payloads; domain_models.py: what services work with
└── prompts/         # .prompt files (system + instruction)
```
