# API Reference

Public API for the `avs-blueprint-agents` framework (Python 3.13+).

All primary classes are exported from `blueprint.agents`:

```python
from blueprint.agents import AppBuilder, AgentBuilder, AgentRuntime, Config
```

---

## AppBuilder

**Module:** `blueprint.agents.app_builder`

Fluent builder that assembles a FastAPI application from handlers, services, agents, APIs, and schedulers.

### Constructor

```python
AppBuilder(config: Config)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `config` | `Config` | Application configuration instance. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `with_handler(handler, *, name=None)` | `AppBuilder` | Register an event handler. |
| `with_service(service, *, name=None)` | `AppBuilder` | Register a service component. |
| `with_agent(agent, *, name=None)` | `AppBuilder` | Register an agent component. |
| `with_rest_api(api, *, name=None)` | `AppBuilder` | Register a REST API controller. |
| `with_scheduler(scheduler, *, name=None)` | `AppBuilder` | Register a scheduled task. |
| `with_cache(enabled=True, enable_locking=True)` | `AppBuilder` | Enable or configure the disk cache. |
| `with_health_checker(name, checker)` | `AppBuilder` | Add a named health-check probe. |
| `build()` | `FastAPI` | Finalize and return the configured FastAPI application. |

### Usage

```python
config = Config()
app = (
    AppBuilder(config)
    .with_service(MyService)
    .with_agent(MyAgent)
    .with_handler(MyHandler)
    .with_rest_api(MyApi)
    .with_cache()
    .build()
)
```

---

## Config

**Module:** `blueprint.agents.config`

Loads and provides access to application settings from `settings.toml` files and environment variables.

### Constructor

```python
Config(settings_files=None, root_path=None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `settings_files` | `list[str] \| None` | `None` | Paths to settings files. Uses default discovery when `None`. |
| `root_path` | `str \| None` | `None` | Root directory for resolving relative paths. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get(key, default=None)` | `Any` | Retrieve a raw configuration value by key. |
| `get_ai_config(runtime_name="default")` | `AIConfig` | Get AI/model configuration for a named runtime. |
| `get_prompt_config(runtime_name=None)` | `PromptConfig` | Get prompt file configuration. |
| `get_cache_config()` | `CacheConfig` | Get disk cache configuration. |
| `get_event_publishing_config()` | `EventPublishingConfig` | Get event publishing / topic mapping configuration. |
| `get_observability_config()` | `ObservabilityConfig` | Get OpenTelemetry and logging configuration. |
| `get_runtime_config(runtime_name="default")` | `dict` | Get the raw runtime configuration dict for a named runtime. |
| `validate()` | `bool` | Validate the configuration. Returns `True` if valid. |
| `get_package_root()` | `Path` | Return the resolved package root directory. |

---

## AgentBuilder

**Module:** `blueprint.agents.agent.agent_builder`

Fluent builder for constructing an `AgentRuntime` instance with a model, prompts, tools, and metrics.

### Constructor

```python
AgentBuilder(config, runtime_name="default", meter=None, package_root=None)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `config` | `Config` | -- | Application configuration instance. |
| `runtime_name` | `str` | `"default"` | Name of the runtime configuration section to use. |
| `meter` | `Meter \| None` | `None` | OpenTelemetry meter for recording metrics. |
| `package_root` | `Path \| None` | `None` | Root path for locating prompt files. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `with_model_from_config(model_name="")` | `AgentBuilder` | Configure the model from the runtime config section. Optional `model_name` override. |
| `with_system_prompt(name=None)` | `AgentBuilder` | Load a system prompt file by name. Uses the configured default when `None`. |
| `with_tools(tools: list[Tool])` | `AgentBuilder` | Register a list of pydantic-ai `Tool` objects. |
| `with_tool(name, function)` | `AgentBuilder` | Register a single tool by name and callable. |
| `with_result_type(result_type: type[BaseModel])` | `AgentBuilder` | Set the structured result type (Pydantic model). |
| `with_deps_type(deps_type)` | `AgentBuilder` | Set the dependency-injection type for the agent. |
| `with_metrics(enabled=True)` | `AgentBuilder` | Enable or disable automatic metrics recording. |
| `build(**kwargs)` | `AgentRuntime` | Build and return the configured `AgentRuntime`. |

### Static Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `extract_response_text(result)` | `str` | Extract the text content from an `AgentRunResult`. |
| `extract_usage_info(result)` | `dict` | Extract token usage information from an `AgentRunResult`. |

### Usage

```python
agent = (
    AgentBuilder(config, runtime_name="default")
    .with_model_from_config()
    .with_system_prompt()
    .with_tools([my_tool])
    .with_metrics()
    .build()
)
```

---

## AgentRuntime

**Module:** `blueprint.agents.agent.agent_runtime`

**Extends:** `pydantic_ai.Agent`, `Component`

Runtime wrapper around a pydantic-ai Agent. Adds prompt loading, metric recording, and lifecycle hooks.

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `async run(user_prompt, *, model_settings=None, **kwargs)` | `AgentRunResult` | Execute the agent with a user prompt. Accepts optional `model_settings` override and additional keyword arguments forwarded to the underlying agent. |
| `get_model_settings()` | `ModelSettings` | Return the current model settings (temperature, max tokens, etc.). |
| `record_metrics(result, duration_ms, model_name=None)` | `None` | Record execution metrics (latency, token usage) for a completed run. |
| `get_prompt(prompt_name, path="")` | `str` | Load a prompt template by name and optional subdirectory path. |
| `on_startup()` | `None` | Lifecycle hook called when the application starts. |
| `on_shutdown()` | `None` | Lifecycle hook called when the application shuts down. |

---

## EventHandlerBase

**Module:** `blueprint.agents.handler.event_handler_base`

Abstract base class for event handlers. Subclass this to process incoming events from the event bus.

### Constructor

```python
EventHandlerBase(priority=100)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `priority` | `int` | `100` | Handler execution priority. Lower values execute first. |

### Abstract Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `can_handle_event(event, context)` | `bool` | Return `True` if this handler should process the given event. |
| `handle_event(event, context)` | `Any \| HandlerResult \| list[HandlerResult] \| None` | Process the event. Return a `HandlerResult` to publish follow-up events, or `None`. |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_published_event_types()` | `tuple[str, str] \| None` | Declare the event types this handler publishes. Returns `(event_type, topic)` or `None`. |

### Usage

```python
class MyHandler(EventHandlerBase):
    def can_handle_event(self, event, context):
        return event.type == "my.event.v1"

    def handle_event(self, event, context):
        # process event
        return HandlerResult(event_type="my.result.v1", data={"ok": True})
```

---

## ServiceBase

**Module:** `blueprint.agents.services.service_base`

Base class for long-lived service components. Provides lifecycle hooks and access to the component registry.

### Constructor

```python
ServiceBase()
```

### Inherited Members

| Member | Type | Description |
|--------|------|-------------|
| `self.registry` | `Registry` | Access to the shared component registry. |
| `self.config` | `Config` | Application configuration. |
| `on_startup()` | method | Called when the application starts. Override for initialization logic. |
| `on_shutdown()` | method | Called when the application shuts down. Override for cleanup logic. |

---

## RestApiBase

**Module:** `blueprint.agents.io.api.rest_api_base`

Base class for REST API controllers. Routes are declared with static decorators and automatically mounted on the FastAPI application.

### Constructor

```python
RestApiBase()
```

### Static Decorators

Use these to decorate methods on your subclass:

| Decorator | Description |
|-----------|-------------|
| `@RestApiBase.get(path, **kwargs)` | Register a GET endpoint. |
| `@RestApiBase.post(path, **kwargs)` | Register a POST endpoint. |
| `@RestApiBase.put(path, **kwargs)` | Register a PUT endpoint. |
| `@RestApiBase.delete(path, **kwargs)` | Register a DELETE endpoint. |
| `@RestApiBase.patch(path, **kwargs)` | Register a PATCH endpoint. |

`**kwargs` are forwarded to the underlying FastAPI route registration.

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `router` | `APIRouter` | The FastAPI router containing all declared routes. |

### Inherited Members

| Member | Type | Description |
|--------|------|-------------|
| `self.registry` | `Registry` | Component registry. |
| `get_registry()` | method | Returns the component registry. |

### Usage

```python
class ItemsApi(RestApiBase):
    @RestApiBase.get("/items")
    async def list_items(self):
        return {"items": []}

    @RestApiBase.post("/items")
    async def create_item(self, body: ItemCreate):
        return {"id": "new"}
```

---

## SchedulerBase

**Module:** `blueprint.agents.io.api.scheduling.scheduler`

Base class for cron-scheduled tasks. Each scheduler automatically exposes a manual trigger endpoint.

### Constructor

```python
SchedulerBase(crontab: str)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `crontab` | `str` | Cron expression defining the schedule (e.g., `"*/5 * * * *"`). |

### Abstract Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `tick()` | `None` | Called on each scheduled invocation. Implement your task logic here. |

### Auto-generated Endpoint

Each registered scheduler exposes:

```
POST /{name}/trigger
```

This endpoint allows manual invocation of the `tick()` method outside the cron schedule.

---

## Registry

**Module:** `blueprint.agents.component.registry`

Central component registry. Provides lookup for services, agents, and other components by name or class.

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `get_service(name_or_class)` | `ServiceBase` | Retrieve a registered service by name (str) or class. |
| `get_agent(name)` | `AgentRuntime` | Retrieve a registered agent by name. |
| `get_component(name_or_class)` | `Component` | Retrieve any registered component by name or class. |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `cache_service` | `CacheService` | The shared cache service instance. |
| `correlation_context` | `CorrelationContext` | The current correlation/trace context. |
