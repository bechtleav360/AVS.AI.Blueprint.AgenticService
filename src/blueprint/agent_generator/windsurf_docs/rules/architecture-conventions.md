---
trigger: always_on
---

# Blueprint Agents Architecture Conventions

## Component-Based Architecture

All application logic MUST extend one of five base classes from `blueprint.agents.base`:

- **BusinessService** - Domain logic, state management, business rules
- **EventHandler** - CloudEvent processing (chain-of-responsibility pattern)
- **RestApi** - HTTP endpoints via FastAPI
- **AgentRuntime** - LLM agents (wraps pydantic-ai Agent)
- **Scheduler** - Background cron-based tasks

All inherit from `Component` base class providing:
- `get_config()` - Access to dynaconf-backed configuration
- `get_registry()` - Access to ComponentRegistry for dependency resolution
- `on_startup()` / `on_shutdown()` - Lifecycle hooks

## Dependency Injection Rules

**NEVER instantiate components inside other components.**

✅ **Correct** - Resolve via registry in `on_startup()`:
```python
class MyHandler(EventHandler):
    async def on_startup(self) -> None:
        self._service = self.get_registry().get_service(MyService)
        self._agent = self.get_registry().get_agent("my_agent")
```

❌ **Wrong** - Direct instantiation:
```python
class MyHandler(EventHandler):
    def __init__(self) -> None:
        self._service = MyService()  # NEVER DO THIS
```

❌ **Wrong** - Registry access in `__init__`:
```python
class MyHandler(EventHandler):
    def __init__(self) -> None:
        self._service = self.get_registry().get_service(MyService)  # Registry not linked yet!
```

## Registration Order

Register dependencies BEFORE components that use them:

```python
app = (
    AppBuilder(config)
    .with_service(MyService())        # 1. Services first
    .with_agent(my_agent)             # 2. Agents
    .with_handler(MyHandler())        # 3. Handlers (depend on services/agents)
    .with_scheduler(MyScheduler())    # 4. Schedulers (depend on services)
    .with_rest_api(MyApi())           # 5. REST APIs (depend on services)
    .build()
)
```

## Naming Convention

Every component MUST pass a unique, stable name to `super().__init__()`:

```python
class InvoiceService(BusinessService):
    def __init__(self) -> None:
        super().__init__("invoice_service")  # Used as registry key
```

Use snake_case for component names. The name is used for registry lookups.

## Configuration Access

Read settings in `on_startup()` or lazy methods, NEVER in `__init__`:

✅ **Correct**:
```python
async def on_startup(self) -> None:
    cfg = self.get_config()
    self._api_url = cfg.get("external_api_url")
```

❌ **Wrong**:
```python
def __init__(self) -> None:
    super().__init__("my_service")
    cfg = self.get_config()  # Config not linked yet!
```

## No Global State

- NO module-level variables holding component instances
- NO singleton patterns (except AppBuilder/ComponentRegistry)
- NO direct imports between component modules - use registry

## Directory Layout

```
src/
├── main.py                    # AppBuilder wiring ONLY
├── api/
│   └── my_api.py             # One RestApi subclass per file
├── handlers/
│   └── my_handler.py         # One EventHandler subclass per file
├── services/
│   └── my_service.py         # One BusinessService subclass per file
├── schedulers/
│   └── my_scheduler.py       # One Scheduler subclass per file
├── agents/
│   └── my_agent.py           # Agent builder code
├── models/
│   └── schemas.py            # Pydantic models
└── prompts/
    └── system.prompt         # Prompt files
```

## Dependency Flow

Dependencies flow DOWNWARD only:
- Handlers/APIs/Schedulers → Services + Agents
- Services → Other Services (if needed)
- Agents are self-contained

NEVER reverse the flow (services should not depend on handlers/APIs).

## Type Hints

Use type retrieval for better IDE support:

✅ **Preferred**:
```python
service: InvoiceService = self.get_registry().get_service(InvoiceService)
```

✅ **Also valid**:
```python
service = self.get_registry().get_service("invoice_service")
```
