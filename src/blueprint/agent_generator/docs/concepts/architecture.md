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

An agent is a **declaration**: `src/main.py` records what the agent is made of, and the host builds
it -- `create_app()` when it runs on its own, `python -m blueprint.agents.entrypoint` when it is one
agent of a group (see [multi-agent setup](../guides/multi-agent-setup.md)).

```python
from pathlib import Path

from blueprint.agents import AgentBuilder, AppBuilder, Config

from my_app.apis import QueryApi
from my_app.handlers import EnrichHandler, IngestHandler
from my_app.schedulers import CleanupScheduler
from my_app.services import EmbeddingService, StorageService

research = (
    AgentBuilder(runtime_name="research")
    .with_model_from_config()
    .with_system_prompt("research_system")
)

agent = (
    AppBuilder()
    .with_service(EmbeddingService)
    .with_service(StorageService)
    .with_agent(research, name="research")
    .with_handler(IngestHandler)
    .with_handler(EnrichHandler)
    .with_rest_api(QueryApi)
    .with_scheduler(CleanupScheduler)
    .with_cache()
)


def create_app():
    return agent.build(Config(settings_files=["settings.toml", ".secrets.toml"], root_path=str(Path(__file__).parent.parent)))
```

### Builder Methods

Every `with_*` call records; nothing is constructed until `build()`. Components are passed as
**classes** -- a group and `create_app()` refuse an instance, because it would exist before any namespace does.

- `.with_service(ServiceClass)` -- Register a service. Services start before handlers and agents, so they are available for dependency resolution.
- `.with_agent(agent_builder, name="...")` -- Register an AI agent runtime from an unbuilt `AgentBuilder`. The name is the registry key services resolve it by.
- `.with_handler(HandlerClass)` -- Register an event handler. Handlers are sorted by priority at runtime; equal priorities keep declaration order.
- `.with_rest_api(ApiClass)` -- Register a REST API module. Routes are mounted on the shared FastAPI instance.
- `.with_scheduler(SchedulerClass)` -- Register a scheduled task. Schedulers start after the APIs and stop before them.
- `.with_cache()` -- Enable the built-in cache service. Once enabled, it is accessible through the registry.
- `.build(config)` -- Validate configuration, instantiate all components, and return the FastAPI application. Single use.

## Component Registry

The component registry is a central service locator that all components share. Components are automatically registered during their `__init__` phase, and the registry becomes fully populated before `on_startup()` is called on any component.

### Resolving Components

```python
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.services.service_base import ServiceBase


class IngestHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        # A handler resolves the one service it delegates to -- nothing else.
        self._service = self.registry.get_service(EmbeddingService)


class EmbeddingService(ServiceBase):
    async def on_startup(self) -> None:
        # Agents and the cache are resolved by services, which hold the business logic.
        self._research = self.registry.get_agent("research")
        self._cache = self.registry.cache_service  # if enabled via .with_cache()
```

### Registry Methods

| Method | Description |
|---|---|
| `self.registry.get_service(ServiceClass)` | Resolve a service instance by its class type |
| `self.registry.get_agent(name)` | Resolve an agent runtime by its registered name |
| `self.registry.cache_service` | This agent's default cache (declared with `.with_cache()`) |

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

The following example shows all five component types. The handler only translates; the service
decides, including whether an event needs work at all.

```python
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from blueprint.agents import AgentBuilder, AppBuilder, Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
from blueprint.agents.services.service_base import ServiceBase


class DocumentReceived(BaseModel):
    """DTO: the payload of a document.received event."""

    content: str


# -- Service: all business logic --
class SummarizationService(ServiceBase):
    async def on_startup(self) -> None:
        self._agent = self.registry.get_agent("summarizer")

    async def on_shutdown(self) -> None:
        pass

    async def summarize(self, text: str) -> str | None:
        """None: the document is too short to need a summary."""
        if len(text) < 200:
            return None
        result = await self._agent.run(text)
        return str(result.output)


# -- Handler: extract, one service call, result --
class DocumentHandler(EventHandlerBase):
    def __init__(self) -> None:
        super().__init__(priority=10)

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(SummarizationService)

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "document.received"

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult:
        payload = self.extract_payload(event, DocumentReceived)
        summary = await self._service.summarize(payload.content)
        if summary is None:
            return HandlerResult.skipped("document too short to summarise")
        return HandlerResult(event_type="document.summarized", data={"summary": summary})


# -- REST API --
class StatusApi(RestApiBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/status")
    async def get_status(self) -> dict[str, str]:
        return {"status": "operational"}


# -- Scheduler --
class PurgeScheduler(SchedulerBase):
    def __init__(self) -> None:
        super().__init__(crontab="0 * * * *")

    async def on_startup(self) -> None:
        self._cache = self.registry.cache_service
        await super().on_startup()  # required: without it the scheduler never runs

    async def on_shutdown(self) -> None:
        await super().on_shutdown()

    async def tick(self) -> None:
        self._cache.clear("temp")


# -- Declaration (src/main.py) --
summarizer = AgentBuilder(runtime_name="summarizer").with_model_from_config().with_system_prompt("summarizer_system")

agent = (
    AppBuilder()
    .with_service(SummarizationService)
    .with_agent(summarizer, name="summarizer")
    .with_handler(DocumentHandler)
    .with_rest_api(StatusApi)
    .with_scheduler(PurgeScheduler)
    .with_cache()
)


def create_app():
    return agent.build(Config(settings_files=["settings.toml", ".secrets.toml"], root_path=str(Path(__file__).parent.parent)))
```

A scheduler also needs `scheduler_mode` in `settings.toml` (no default; see
[schedulers](../components/schedulers.md)).
