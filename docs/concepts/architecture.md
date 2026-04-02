# Architecture

Blueprint Agents is built on a component-based architecture where discrete building blocks are wired together through a fluent builder API and connected at runtime via a central component registry.

## Component Model

The framework provides five base classes that serve as the foundation for all application components:

| Base Class | Purpose |
|---|---|
| `EventHandlerBase` | Process incoming CloudEvents in a chain-of-responsibility pattern |
| `ServiceBase` | Encapsulate business logic, integrations, and shared state |
| `RestApiBase` | Define custom FastAPI routes exposed by the application |
| `AgentRuntime` | Wrap an AI model with tools, prompts, and orchestration logic |
| `SchedulerBase` | Execute recurring or delayed tasks on a configurable schedule |

Each base class follows the same lifecycle contract and participates in the component registry, making cross-component communication straightforward.

## AppBuilder Fluent API

Applications are assembled using `AppBuilder`, which exposes a fluent interface for registering components and producing a configured application instance.

```python
from blueprint.agents import AppBuilder, Config

from my_app.handlers import IngestHandler, EnrichHandler
from my_app.services import EmbeddingService, StorageService
from my_app.agents import ResearchAgent
from my_app.apis import QueryApi
from my_app.schedulers import CleanupScheduler

config = Config(settings_files=["settings.toml", "secrets.toml"])

app = (
    AppBuilder(config)
    .with_service(EmbeddingService)
    .with_service(StorageService)
    .with_handler(IngestHandler)
    .with_handler(EnrichHandler)
    .with_agent("research", ResearchAgent)
    .with_rest_api(QueryApi)
    .with_scheduler(CleanupScheduler)
    .with_cache()
    .build()
)
```

### Builder Methods

- `.with_handler(HandlerClass)` -- Register an event handler. Handlers are instantiated in registration order and sorted by priority at runtime.
- `.with_service(ServiceClass)` -- Register a shared service. Services start before handlers and agents, so they are available for dependency resolution.
- `.with_agent(name, AgentClass)` -- Register a named AI agent runtime. The name is used for configuration lookup and registry resolution.
- `.with_rest_api(ApiClass)` -- Register a REST API module. Routes are mounted on the shared FastAPI instance.
- `.with_scheduler(SchedulerClass)` -- Register a scheduled task. Schedulers start last and are the first to shut down.
- `.with_cache()` -- Enable the built-in disk cache service. Once enabled, it is accessible through the registry.
- `.build()` -- Validate configuration, instantiate all components, and return the runnable application.

## Component Registry

The component registry is a central service locator that all components share. Components are automatically registered during their `__init__` phase, and the registry becomes fully populated before `on_startup()` is called on any component.

### Resolving Components

```python
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from my_app.services import EmbeddingService


class IngestHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        # Resolve a service by its class
        self.embedding = self.registry.get_service(EmbeddingService)

        # Resolve an agent by its registered name
        self.research_agent = self.registry.get_agent("research")

        # Access the cache (if enabled via .with_cache())
        self.cache = self.registry.cache_service
```

### Registry Methods

| Method | Description |
|---|---|
| `self.registry.get_service(ServiceClass)` | Resolve a service instance by its class type |
| `self.registry.get_agent(name)` | Resolve an agent runtime by its registered name |
| `self.registry.cache_service` | Access the shared cache service instance |

## Component Lifecycle

Every component follows a three-phase lifecycle:

```
__init__() --> on_startup() --> running --> on_shutdown()
```

### Phase Details

1. **`__init__()`** -- The component is instantiated and registered in the component registry. Configuration and other components are **not** available at this stage. Do not attempt to access `self.registry` or `self.config` here.

2. **`on_startup()`** -- Called after all components have been instantiated. The registry is fully populated and configuration is accessible. Use this phase to resolve dependencies, open connections, and perform initialization.

3. **Running** -- The component is active and processing work. Event handlers receive events, schedulers fire tasks, and REST APIs serve requests.

4. **`on_shutdown()`** -- Called during graceful shutdown. Use this phase to close connections, flush buffers, and release resources.

### Important Constraint

The registry and config are **not** available during `__init__`. Any attempt to resolve dependencies or read configuration in the constructor will fail. All such work must be deferred to `on_startup()`.

```python
from blueprint.agents.services.service_base import ServiceBase


class StorageService(ServiceBase):
    def __init__(self) -> None:
        super().__init__()
        # DO NOT access self.registry or self.config here.
        self.client = None

    async def on_startup(self) -> None:
        # Safe to access config and registry from this point onward.
        connection_string = self.config.get("storage_connection_string")
        self.client = await create_storage_client(connection_string)

    async def on_shutdown(self) -> None:
        if self.client:
            await self.client.close()
```

## Startup and Shutdown Order

Components start in a deterministic order that ensures dependencies are available before dependents initialize:

### Startup Order

1. **Clients** -- Low-level HTTP/gRPC clients
2. **Services** -- Business logic and integrations
3. **Handlers** -- Event processing chains
4. **Agents** -- AI agent runtimes
5. **REST APIs** -- HTTP endpoints
6. **Schedulers** -- Recurring tasks
7. **Eventing** -- Event bus subscriptions activated last

### Shutdown Order

Shutdown proceeds in **reverse** order. Eventing is deactivated first so no new events arrive, then schedulers stop, APIs drain, and so on down to clients.

This ordering guarantees that a handler's `on_startup()` can safely call `self.registry.get_service(...)` because all services have already completed their own `on_startup()`.

## Full Wiring Example

The following example shows a complete application with all five component types wired together:

```python
from blueprint.agents import AppBuilder, AgentBuilder, AgentRuntime, Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase
from blueprint.agents.models.events import CloudEvent, HandlerResult


# -- Service --
class SummarizationService(ServiceBase):
    async def on_startup(self) -> None:
        self.agent = self.registry.get_agent("summarizer")

    async def summarize(self, text: str) -> str:
        return await self.agent.run(text)


# -- Handler --
class DocumentHandler(EventHandlerBase):
    priority = 10

    async def on_startup(self) -> None:
        self.svc = self.registry.get_service(SummarizationService)

    def can_handle_event(self, event: CloudEvent) -> bool:
        return event.type == "document.received"

    async def handle_event(self, event: CloudEvent) -> HandlerResult:
        summary = await self.svc.summarize(event.data["content"])
        return HandlerResult(event_type="document.summarized", data={"summary": summary})

    def get_published_event_types(self) -> list[str]:
        return ["document.summarized", "document.error"]


# -- REST API --
class StatusApi(RestApiBase):
    def register_routes(self, router) -> None:
        @router.get("/status")
        async def get_status():
            return {"status": "operational"}


# -- Scheduler --
class PurgeScheduler(SchedulerBase):
    async def on_startup(self) -> None:
        self.cache = self.registry.cache_service

    async def execute(self) -> None:
        await self.cache.clear("temp")


# -- Application assembly --
config = Config(settings_files=["settings.toml", "secrets.toml"])

app = (
    AppBuilder(config)
    .with_service(SummarizationService)
    .with_handler(DocumentHandler)
    .with_agent("summarizer", AgentBuilder.from_config(config, "summarizer"))
    .with_rest_api(StatusApi)
    .with_scheduler(PurgeScheduler)
    .with_cache()
    .build()
)
```
