# Architecture Best Practices

## Component model

Every piece of application logic lives in a class that extends one of the five
base classes from `blueprint.agents.base`:

| Base class | Purpose | Registered via |
|------------|---------|----------------|
| `BusinessService` | Stateless or stateful domain logic | `AppBuilder.with_service()` |
| `EventHandler` | Reacts to CloudEvents (chain-of-responsibility) | `AppBuilder.with_handler()` |
| `RestApi` | Exposes HTTP endpoints via FastAPI | `AppBuilder.with_rest_api()` |
| `AgentRuntime` | Wraps a pydantic-ai LLM agent | `AppBuilder.with_agent()` |
| `Scheduler` | Runs background work on a cron schedule | `AppBuilder.with_scheduler()` |

All five inherit from `Component`, which provides:
- `get_config()` → access to `Config` (dynaconf-backed settings)
- `get_registry()` → access to `ComponentRegistry` (all other components)
- `link_config()` / `link_component_registry()` → called by AppBuilder at startup
- `on_startup()` / `on_shutdown()` → lifecycle hooks

**Never instantiate one component inside another.** Always resolve dependencies
through the registry in `on_startup()`.

## Dependency direction

```
AppBuilder
  └── ComponentRegistry
        ├── BusinessService  ← no dependencies on other components at construction time
        ├── EventHandler     ← resolves agents/services in on_startup()
        ├── RestApi          ← resolves services in on_startup()
        ├── AgentRuntime     ← resolves nothing (self-contained)
        └── Scheduler        ← resolves services in on_startup()
```

Dependencies flow **downward only**: handlers/APIs/schedulers depend on services
and agents, never the other way around.

## Registration order in AppBuilder

Register dependencies **before** the components that use them:

```python
app = (
    AppBuilder(config=config)
    .with_service(my_service)        # 1. services first
    .with_agent(my_agent)            # 2. agents
    .with_handler(MyHandler())       # 3. handlers (depend on agents + services)
    .with_scheduler(MyScheduler())   # 4. schedulers (depend on services)
    .with_rest_api(MyApi())          # 5. REST APIs (depend on services)
    .build()
)
```

## Resolving dependencies in on_startup()

```python
class MyHandler(EventHandler):
    async def on_startup(self) -> None:
        # Resolve once at startup, store as instance attribute
        self._service = self.get_registry().get_service("my_service")
        self._agent   = self.get_registry().get_agent("my_agent")
```

Never call `get_registry()` in `__init__` — the registry is not linked yet.

## Naming convention

Every component must pass a stable, unique name to `super().__init__()`:

```python
class InvoiceService(BusinessService):
    def __init__(self) -> None:
        super().__init__("invoice_service")   # used as registry key
```

The name is the key used by `get_service()`, `get_agent()`, etc.

## Configuration access

Read settings inside `on_startup()` or lazy methods, not in `__init__`:

```python
async def on_startup(self) -> None:
    cfg = self.get_config()
    self._api_url = cfg.get("external_api_url")
```

## No global state

- No module-level variables holding component instances
- No singleton patterns outside of `AppBuilder`/`ComponentRegistry`
- No direct imports between component modules — use the registry

## File layout convention

```
src/
├── main.py                 # AppBuilder wiring only
├── api/
│   ├── __init__.py
│   └── routes.py           # one RestApi subclass per file
├── handlers/
│   ├── __init__.py
│   └── my_handler.py       # one EventHandler subclass per file
├── services/
│   ├── __init__.py
│   └── my_service.py       # one BusinessService subclass per file
├── schedulers/
│   ├── __init__.py
│   └── my_scheduler.py     # one Scheduler subclass per file
└── models/
    ├── __init__.py
    └── schemas.py           # Pydantic models
```
