# API Reference

Complete reference for the Agent Blueprint framework.

---

## AppBuilder

Main entry point for building FastAPI applications.

### Methods

#### `with_handler(handler: type[EventHandler] | EventHandler) -> AppBuilder`

Register an event handler.

```python
app_builder.with_handler(MyEventHandler)
```

#### `with_service(service: BusinessService) -> AppBuilder`

Register a business service.

```python
app_builder.with_service(MyService())
```

#### `with_agent(agent: AgentRuntime) -> AppBuilder`

Register an LLM agent.

```python
app_builder.with_agent(my_agent)
```

#### `with_rest_api(api: RestApi) -> AppBuilder`

Register a custom REST API.

```python
app_builder.with_rest_api(MyRestApi())
```

#### `with_cache(enabled: bool = True) -> AppBuilder`

Enable persistent caching.

```python
app_builder.with_cache()
```

#### `build() -> FastAPI`

Build and return the FastAPI application.

```python
app = app_builder.build()
```

---

## EventHandler

Base class for event handlers.

### Abstract Methods

#### `async can_handle_event(event: CloudEvent, context) -> bool`

Determine if this handler can process the event.

```python
async def can_handle_event(self, event: CloudEvent, context) -> bool:
    return event.get_type() == "user.created"
```

#### `async handle_event(event: CloudEvent, context) -> HandlerResult | list[HandlerResult] | None`

Process the event and optionally return results to publish.

```python
async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
    # Process event
    result = await self.process(event.get_data())

    # Return result to publish new event
    return HandlerResult(
        event_type="user.processed",
        data=result
    )
```

### Properties

#### `_component_registry: ComponentRegistry`

Access other registered components.

```python
agent = self._registry.get_agent("my_agent")
service = self._registry.get_service("my_service")
```

---

## RestApi

Base class for REST API endpoints.

### Abstract Methods

#### `def _register_routes()`

Register FastAPI routes.

```python
def _register_routes(self):
    @self.router.post("/users")
    async def create_user(request: UserRequest):
        service = self._registry.get_service("user_service")
        return await service.create_user(request)
```

#### `async on_startup()`

Called when service starts.

```python
async def on_startup(self):
    # Initialize resources
    pass
```

#### `async on_shutdown()`

Called when service stops.

```python
async def on_shutdown(self):
    # Clean up resources
    pass
```

### Properties

#### `router: APIRouter`

FastAPI router for registering routes.

```python
@self.router.get("/health")
async def health():
    return {"status": "ok"}
```

#### `_component_registry: ComponentRegistry`

Access other registered components.

---

## BusinessService

Base class for business logic services.

### Abstract Methods

#### `def get_name() -> str`

Return the service name.

```python
def get_name(self) -> str:
    return "user_service"
```

#### `async on_startup()`

Called when service starts.

```python
async def on_startup(self):
    # Connect to database
    pass
```

#### `async on_shutdown()`

Called when service stops.

```python
async def on_shutdown(self):
    # Close database connection
    pass
```

---

## AgentBuilder

Builder for creating LLM agents.

### Methods

#### `with_model(model_name: str) -> AgentBuilder`

Configure with a specific model name.

```python
builder.with_model("gpt-4")
```

#### `with_model_from_config(runtime_name: str | None = None) -> AgentBuilder`

Load model from configuration.

```python
builder.with_model_from_config("invoice_analyzer")
```

#### `with_system_prompt_text(text: str) -> AgentBuilder`

Set system prompt as inline text.

```python
builder.with_system_prompt_text("You are a helpful assistant")
```

#### `with_system_prompt_file(name: str) -> AgentBuilder`

Load system prompt from file.

```python
builder.with_system_prompt_file("system")
```

#### `with_tools(tools: list[Tool]) -> AgentBuilder`

Register tools the agent can call.

```python
builder.with_tools([calculate_tool, search_tool])
```

#### `with_result_type(result_type: type[BaseModel]) -> AgentBuilder`

Set Pydantic model for structured outputs.

```python
builder.with_result_type(InvoiceData)
```

#### `with_metrics(enabled: bool = True) -> AgentBuilder`

Enable/disable metrics logging.

```python
builder.with_metrics(True)
```

#### `build(**kwargs) -> AgentRuntime`

Build and return the agent.

```python
agent = builder.build()
```

---

## HandlerResult

Result returned from event handlers.

### Fields

#### `event_type: str`

Type of event to publish (e.g., "user.processed").

#### `data: dict[str, Any]`

Event data payload.

#### `metadata: dict[str, Any] | None`

Optional metadata.

### Example

```python
return HandlerResult(
    event_type="user.processed",
    data={"user_id": 123, "status": "active"},
    metadata={"source": "handler"}
)
```

---

## Config

Application configuration loader.

### Methods

#### `get_ai_config(runtime_name: str) -> AIConfig`

Get AI model configuration.

```python
ai_config = config.get_ai_config("invoice_analyzer")
```

#### `get_cache_config() -> CacheConfig`

Get cache configuration.

```python
cache_config = config.get_cache_config()
```

#### `get_prompt_config(runtime_name: str) -> PromptConfig`

Get prompt configuration.

```python
prompt_config = config.get_prompt_config("invoice_analyzer")
```

#### `get(key: str, default: Any = None) -> Any`

Get configuration value by key.

```python
app_name = config.get("app_name", "my-app")
```

---

## Cache API Endpoints

### GET /api/cache/stats

Get cache statistics.

**Response:**
```json
{
  "size": 42,
  "cache_dir": "/path/to/cache",
  "ttl_tracked_keys": 10,
  "size_limit": 1000000000,
  "eviction_policy": "least-recently-used"
}
```

### GET /api/cache/namespaces

List all cache namespaces.

**Response:**
```json
{
  "namespaces": ["default", "users", "invoices"],
  "count": 3
}
```

### POST /api/cache/evict

Clear cache for a namespace.

**Request:**
```json
{
  "namespace": "users"
}
```

**Response:**
```json
{
  "status": "ok",
  "namespace": "users",
  "message": "Cache cleared for namespace 'users'"
}
```

---

## Environment Variables

### Required

- `OPENAI_API_KEY` — OpenAI API key (if using OpenAI models)

### Optional

- `LOG_LEVEL` — Logging level (DEBUG, INFO, WARNING, ERROR)
- `DAPR_HTTP_PORT` — Dapr HTTP port (default: 3500)
- `DAPR_GRPC_PORT` — Dapr gRPC port (default: 50001)

---

## Configuration File Format

### settings.toml

```toml
[default]
app_name = "my-app"
log_level = "INFO"

[default.ai.default]
provider = "openai"
model_name = "gpt-4"

[default.cache]
cache_dir = ".cache/blueprint"
size_limit = 1000000000
eviction_policy = "least-recently-used"

[default.event_publishing]
enabled = true
dapr_http_port = 3500

[[default.event_publishing.topic_mapping]]
topic = "user.created"
subscription_path = "/dapr/subscribe/user.created"
```

### secrets.toml

```toml
[default.ai.default]
api_key = "${OPENAI_API_KEY}"
```

---

## Error Handling

### Common Exceptions

#### `ValueError`

Raised when configuration is invalid or required fields are missing.

```python
try:
    agent = builder.build()
except ValueError as e:
    print(f"Build failed: {e}")
```

#### `RuntimeError`

Raised when component is not registered.

```python
try:
    agent = registry.get_agent("missing")
except RuntimeError as e:
    print(f"Agent not found: {e}")
```

---

## Logging

Enable debug logging in `settings.toml`:

```toml
log_level = "DEBUG"
```

Access logger in your code:

```python
import logging

logger = logging.getLogger(__name__)
logger.info("Processing event: %s", event_type)
logger.debug("Event data: %s", event.get_data())
logger.error("Failed to process: %s", error)
```
