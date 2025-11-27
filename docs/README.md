# Agent Blueprint Documentation

**Welcome!** This documentation helps you build intelligent agents using the Agent Blueprint framework.

> **For Junior Developers:** This documentation is written with you in mind. We explain concepts clearly, provide examples, and guide you step-by-step.

---

## � Quick Start Guides

Choose your path based on what you want to build:

1. **[Simple REST API](guides/01-simple-rest-api.md)** — Build a web service with just REST endpoints (no events, no AI)
2. **[Event-Driven Service](guides/02-event-driven-service.md)** — Add event handlers and Dapr pub/sub for message processing
3. **[AI Agent Service](guides/03-ai-agent-service.md)** — Combine events, handlers, and LLM agents for intelligent processing

---

## 📖 Core Concepts

### The App Builder
The **AppBuilder** is your main entry point. It uses the **builder pattern** to configure and create your FastAPI application:

```python
from blueprint.agents import AppBuilder, Config

config = Config(settings_files=["settings.toml"])
app = (
    AppBuilder(config)
    .with_handler(MyEventHandler)
    .with_agent(my_llm_agent)
    .with_rest_api(MyRestApi())
    .with_cache()
    .build()
)
```

### Four Base Classes

These are the building blocks you'll extend:

- **`EventHandler`** — Process incoming events from message queues (e.g., RabbitMQ via Dapr)
- **`RestApi`** — Define custom REST endpoints for your service
- **`AgentRuntime`** — LLM agents that think and decide (powered by Pydantic AI)
- **`BusinessService`** — Reusable business logic (databases, APIs, calculations)

### Component Registry

The **ComponentRegistry** is an internal registry that stores all your components. You access it inside handlers and services:

```python
class MyHandler(EventHandler):
    async def handle_event(self, event, context):
        # Access other components
        agent = self._component_registry.get_agent("my_agent")
        service = self._component_registry.get_service("my_service")
```

### Event Handlers & Chain of Responsibility

Handlers process events in priority order. Each handler decides:
- **Can I handle this?** → `can_handle_event()` returns True/False
- **What do I do?** → `handle_event()` processes and returns a result
- **Publish or pass?** → Return `HandlerResult` to publish an event, or None to pass to next handler


### Error Handling

When processing events, **always** raise exceptions if anything goes wrong. This ensures that Dapr does not delete the message, as it considers the message as "processed" when the handler returns successfully.

If you catch exceptions inside your handler, Dapr will not know that something went wrong, and it will delete the message. This could lead to data loss or unexpected behavior.

Instead, let exceptions propagate up the call stack to be handled by your application.


```python
class MyHandler(EventHandler):
    async def can_handle_event(self, event, context):
        return event.type == "user.created"

    async def handle_event(self, event, context):
        # Process the event
        try:
            result = process_user(event.data)
        except Exception as e:
            raise e
        # Publish a new event
        return HandlerResult(
            event_type="user.processed",
            data=result
        )
```

### Services for Business Logic

Keep your business logic in **BusinessService** classes. Handlers call them:

```python
class UserService(BusinessService):
    async def create_user(self, email: str) -> User:
        # Your database logic here
        return user

class UserHandler(EventHandler):
    async def handle_event(self, event, context):
        service = self._component_registry.get_service("user_service")
        user = await service.create_user(event.data.email)
```

### LLM Agents & Prompt Loading

**Agents** are AI models that think and make decisions. You configure them with:
- **Model** — Which LLM to use (OpenAI, Anthropic, etc.)
- **System Prompt** — Instructions for the AI ("You are a helpful assistant...")
- **Tools** — Functions the AI can call
- **Output Type** — Pydantic model for structured responses

```python
from blueprint.agents import AgentBuilder

agent = (
    AgentBuilder(config)
    .with_model_from_config("my_agent")  # Load from settings.toml
    .with_system_prompt_file("system")   # Load from prompts/system.prompt
    .with_tools([calculate_tool, search_tool])
    .with_result_type(AnalysisOutput)
    .build()
)
```

**Prompt Loading:** The framework automatically searches for prompts in:
- `<package_root>/prompts/` — Your project's prompts folder
- `<package_root>/src/prompts/` — Alternative location
- Configured search paths in `settings.toml`
- Prompt path configured in environment variable

---

## 🧪 Testing & Debugging

### VS Code Launch Configurations

Run examples directly from VS Code:

1. Open the **Run and Debug** panel (Ctrl+Shift+D)
2. Select a configuration (e.g., "FastAPI: examples/rest_microservice")
3. Press **F5** to start with automatic `pip install`

Available configurations:
- `FastAPI: examples/rest_microservice` — REST API only
- `FastAPI: examples/simple_event_processor` — Event processing
- `FastAPI: examples/trivia_game` — AI agent example
- `FastAPI: examples/complex_agent` — Advanced agent setup

### VS Code Tasks

Run common tasks from the Command Palette (Ctrl+Shift+P):

- **pip:install** — Install project dependencies
- **lint:ruff** — Check code style
- **format:black** — Auto-format code
- **Mypy: Type Check** — Verify type hints

### Debugging with Breakpoints

1. Set a breakpoint by clicking the line number
2. Launch the app with F5
3. The debugger pauses at breakpoints
4. Use the Debug Console to inspect variables

### Testing Your Agent

Run tests with pytest:

```bash
# All tests
pytest tests/unit/ -v

# Specific test file
pytest tests/unit/test_event_handler.py -v

# Specific test
pytest tests/unit/test_event_handler.py::test_handler_processes_event -v
```

---

## 🔧 Configuration

Settings are loaded from `settings.toml` and `secrets.toml`:

```toml
[default]
app_name = "my-agent"
log_level = "INFO"

[default.ai.default]
provider = "openai"
model_name = "gpt-4"
api_key = "${OPENAI_API_KEY}"

[default.cache]
cache_dir = ".cache/blueprint"
size_limit = 1000000000
```

---

## 📚 What's Next?

- **Ready to build?** Start with [Simple REST API](guides/01-simple-rest-api.md)
- **Need more details?** Check the [API Reference](reference/api.md)
- **Something broken?** See [Troubleshooting](troubleshooting.md)

---

*Last updated: 2025-11-26 | For junior Python developers*


