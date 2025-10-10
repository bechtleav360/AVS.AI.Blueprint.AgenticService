# Using the App Builder

**Time to complete:** 15 minutes  
**Difficulty:** Beginner

This guide explains how to use the `AppBuilder` to configure and initialize your agent application.

## What Is the App Builder?

The **App Builder** is a fluent interface for configuring your FastAPI application. Think of it as a recipe:

```python
app = (
    AppBuilder()
    .with_handler(ValidationHandler)      # Add ingredients
    .with_handler(ProcessingHandler)
    .with_agent_runtime(MyAgent)
    .with_rest_api(CustomRestApi)
    .build()                               # Bake the cake!
)
```

## Why Use App Builder?

**Benefits:**
- **Declarative** - Clearly see what your app includes
- **Type-Safe** - Catches errors at startup, not runtime
- **Flexible** - Easy to add/remove components
- **Testable** - Mock components for testing

## Basic Usage

### Minimal Application

The simplest possible application:

```python
from base.src.app_builder import AppBuilder

app = AppBuilder().build()
```

This creates a FastAPI app with:
- Health check endpoints (`/actuators/health`)
- Event processing endpoint (`/events/process`)
- OpenAPI docs (`/docs`)

### Adding Handlers

```python
from base.src.app_builder import AppBuilder
from custom.src.agent.handlers import MyHandler

app = (
    AppBuilder()
    .with_handler(MyHandler)
    .build()
)
```

### Adding Agent Runtime

```python
from base.src.app_builder import AppBuilder
from custom.src.agent.runtime import MyAgentRuntime
from custom.src.agent.handlers import MyHandler

app = (
    AppBuilder()
    .with_handler(MyHandler)
    .with_agent_runtime(MyAgentRuntime, is_default=True)
    .build()
)
```

### Adding REST API

```python
from base.src.app_builder import AppBuilder
from custom.src.api.rest import CustomRestApi
from custom.src.agent.runtime import MyAgentRuntime
from custom.src.agent.handlers import MyHandler

app = (
    AppBuilder()
    .with_handler(MyHandler)
    .with_agent_runtime(MyAgentRuntime, is_default=True)
    .with_rest_api(CustomRestApi)
    .build()
)
```

## Configuration

### Settings Files

The App Builder loads configuration from TOML files:

```python
app = AppBuilder(
    settings_files=["custom/settings.toml", "custom/secrets.toml"],
    root_path="/path/to/project"
).build()
```

**Default behavior:**
- Looks for `settings.toml` in current directory
- Looks for `secrets.toml` in current directory
- Environment variables override file settings

### Configuration Structure

**`settings.toml`** - Non-sensitive configuration:
```toml
[default]
app_name = "invoice-processor"
app_port = 8001
log_level = "INFO"

ai_model_provider = "openai"
ai_model_name = "gpt-4"

[development]
log_level = "DEBUG"

[production]
log_level = "WARNING"
```

**`secrets.toml`** - Sensitive data (not in git):
```toml
[default]
ai_model_api_key = "sk-your-key-here"
database_password = "secret123"
```

### Environment Variables

Override settings with environment variables:

```bash
export APP_NAME="my-agent"
export LOG_LEVEL="DEBUG"
export AI_MODEL_API_KEY="sk-new-key"

python -m uvicorn custom.src.main:app
```

## Component Registration

### Registering Handlers

Handlers are registered in priority order:

```python
app = (
    AppBuilder()
    .with_handler(ValidationHandler)      # priority=10
    .with_handler(EnrichmentHandler)      # priority=20
    .with_handler(AgentInvokerHandler)    # priority=30
    .build()
)
```

**Execution order:** Lower priority runs first (10 → 20 → 30)

### Registering Multiple Runtimes

You can register multiple AI runtimes:

```python
app = (
    AppBuilder()
    .with_agent_runtime(InvoiceAgent, is_default=True)
    .with_agent_runtime(AssetAgent, is_default=False)
    .build()
)
```

**Usage in handlers:**
```python
async def _handle(self, event, context):
    # Use default runtime
    context["use_agent"] = True
    
    # Or specify runtime
    context["use_agent"] = True
    context["agent_name"] = "AssetAgent"
```

### Registering Custom Routers

Add custom FastAPI routers:

```python
from fastapi import APIRouter

custom_router = APIRouter()

@custom_router.get("/custom/endpoint")
async def custom_endpoint():
    return {"message": "Hello!"}

app = (
    AppBuilder()
    .with_router(custom_router, prefix="/api", tags=["custom"])
    .build()
)
```

## Complete Example

Here's a full `custom/src/main.py`:

```python
"""Application entry point."""

import logging
from base.src.app_builder import AppBuilder

# Import your components
from .agent.handlers import (
    ValidationHandler,
    EnrichmentHandler,
    AgentInvokerHandler,
)
from .agent.runtime import InvoiceAgentRuntime
from .api.rest import CustomRestApi

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# Build application
app = (
    AppBuilder(
        settings_files=["settings.toml", "secrets.toml"],
        root_path="."
    )
    # Register handlers (in priority order)
    .with_handler(ValidationHandler)
    .with_handler(EnrichmentHandler)
    .with_handler(AgentInvokerHandler)
    
    # Register AI runtime
    .with_agent_runtime(InvoiceAgentRuntime, is_default=True)
    
    # Register REST API
    .with_rest_api(CustomRestApi)
    
    # Build FastAPI app
    .build()
)

logger.info("Application initialized successfully")

# For development
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

## Application Lifecycle

### Startup

When you run your application:

1. **Configuration Loading**
   - Loads `settings.toml`
   - Loads `secrets.toml`
   - Applies environment variable overrides

2. **Component Initialization**
   - Creates handler instances
   - Creates runtime instances
   - Registers components in registry

3. **FastAPI Setup**
   - Configures routes
   - Sets up middleware
   - Enables OpenAPI docs

4. **Health Checks**
   - Initializes health checkers
   - Tests AI provider connection

### Shutdown

When the application stops:

1. **Cleanup**
   - Closes connections
   - Flushes logs
   - Releases resources

## Built-in Endpoints

The App Builder automatically provides these endpoints:

### Health Checks

**`GET /actuators/health`** - Overall health
```bash
curl http://localhost:8001/actuators/health
```

Response:
```json
{
  "status": "healthy",
  "checks": {
    "ai_provider": "healthy"
  }
}
```

**`GET /actuators/health/liveness`** - Is app running?
```bash
curl http://localhost:8001/actuators/health/liveness
```

**`GET /actuators/health/readiness`** - Is app ready?
```bash
curl http://localhost:8001/actuators/health/readiness
```

### Event Processing

**`POST /events/process`** - Process CloudEvents
```bash
curl -X POST http://localhost:8001/events/process \
  -H "Content-Type: application/json" \
  -d '{
    "specversion": "1.0",
    "type": "invoice.created",
    "source": "test",
    "id": "123",
    "data": {"invoice_id": "INV-001"}
  }'
```

### Documentation

**`GET /docs`** - Interactive API docs (Swagger UI)
**`GET /redoc`** - Alternative API docs (ReDoc)
**`GET /openapi.json`** - OpenAPI schema

## Advanced Configuration

### Custom Health Checks

Add custom health checks:

```python
from base.src.api.actuators import HealthChecker

class DatabaseHealthChecker(HealthChecker):
    async def check(self) -> dict:
        try:
            await self.db.ping()
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

# In main.py
app = (
    AppBuilder()
    .with_health_checker("database", DatabaseHealthChecker())
    .build()
)
```

### Custom Middleware

Add FastAPI middleware:

```python
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

app = AppBuilder().build()

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Custom Logging

Configure structured logging:

```python
import logging
from pythonjsonlogger import jsonlogger

# Configure JSON logging
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)

logger = logging.getLogger()
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# Build app
app = AppBuilder().build()
```

## Testing with App Builder

### Unit Tests

Test individual components:

```python
import pytest
from base.src.app_builder import AppBuilder
from custom.src.agent.handlers import MyHandler

def test_handler_registration():
    """Test that handlers are registered correctly."""
    builder = AppBuilder()
    builder.with_handler(MyHandler)
    
    app = builder.build()
    
    # Access registry
    registry = builder._component_registry
    handlers = registry.get_handlers()
    
    assert len(handlers) == 1
    assert isinstance(handlers[0], MyHandler)
```

### Integration Tests

Test the full application:

```python
import pytest
from fastapi.testclient import TestClient
from custom.src.main import app

client = TestClient(app)

def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/actuators/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_event_processing():
    """Test event processing endpoint."""
    event = {
        "specversion": "1.0",
        "type": "invoice.created",
        "source": "test",
        "id": "test-123",
        "data": {"invoice_id": "INV-001"}
    }
    
    response = client.post("/events/process", json=event)
    assert response.status_code == 200
```

## Common Patterns

### Pattern 1: Environment-Specific Configuration

```python
import os

env = os.getenv("ENVIRONMENT", "development")

app = (
    AppBuilder(
        settings_files=[
            "settings.toml",
            f"settings.{env}.toml",
            "secrets.toml"
        ]
    )
    .with_handler(MyHandler)
    .build()
)
```

### Pattern 2: Conditional Components

```python
from base.src.app_builder import AppBuilder

builder = AppBuilder()

# Always add these
builder.with_handler(ValidationHandler)

# Conditionally add AI
if config.get("enable_ai"):
    builder.with_agent_runtime(MyAgent, is_default=True)

# Conditionally add custom API
if config.get("enable_rest_api"):
    builder.with_rest_api(CustomRestApi)

app = builder.build()
```

### Pattern 3: Plugin Architecture

```python
# Load plugins dynamically
import importlib

plugins = ["plugin1", "plugin2", "plugin3"]

builder = AppBuilder()

for plugin_name in plugins:
    module = importlib.import_module(f"custom.plugins.{plugin_name}")
    handler_class = getattr(module, "Handler")
    builder.with_handler(handler_class)

app = builder.build()
```

## Troubleshooting

### "Module not found" errors

**Cause:** Import paths incorrect

**Solution:** Check your imports:
```python
# Correct
from custom.src.agent.handlers import MyHandler

# Wrong
from agent.handlers import MyHandler
```

### Configuration not loading

**Cause:** Wrong file path or format

**Solution:** Check file exists and is valid TOML:
```bash
# Verify file exists
ls -la custom/settings.toml

# Validate TOML syntax
python -c "import tomli; tomli.load(open('custom/settings.toml', 'rb'))"
```

### Handlers not running

**Cause:** Not registered or wrong priority

**Solution:** Check registration:
```python
# Make sure you call .with_handler()
app = (
    AppBuilder()
    .with_handler(MyHandler)  # Don't forget this!
    .build()
)
```

### Port already in use

**Cause:** Another process using the port

**Solution:** Use different port or kill process:
```bash
# Find process
lsof -i :8001

# Kill process
kill -9 <PID>

# Or use different port
uvicorn custom.src.main:app --port 8002
```

## Best Practices

### 1. Keep main.py Simple

```python
# Good - declarative and clear
app = (
    AppBuilder()
    .with_handler(Handler1)
    .with_handler(Handler2)
    .with_agent_runtime(MyAgent)
    .build()
)

# Bad - too much logic
app = AppBuilder()
if some_condition:
    app.with_handler(Handler1)
else:
    app.with_handler(Handler2)
# ... more complex logic ...
app = app.build()
```

### 2. Use Type Hints

```python
from fastapi import FastAPI
from base.src.app_builder import AppBuilder

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    return (
        AppBuilder()
        .with_handler(MyHandler)
        .build()
    )

app = create_app()
```

### 3. Document Configuration

```toml
# settings.toml

[default]
# Application settings
app_name = "invoice-processor"  # Service name for logging/tracing
app_port = 8001                 # HTTP port

# AI Model settings
ai_model_provider = "openai"    # Provider: openai, vllm, anthropic
ai_model_name = "gpt-4"         # Model to use
ai_model_timeout = 60           # Request timeout in seconds
```

### 4. Validate Configuration

```python
from base.src.app_builder import AppBuilder

builder = AppBuilder()

# Validate required settings
config = builder.config
required = ["ai_model_api_key", "app_name"]

for key in required:
    if not config.get(key):
        raise ValueError(f"Missing required config: {key}")

app = builder.build()
```

## Quick Reference

```python
# Basic app
app = AppBuilder().build()

# With components
app = (
    AppBuilder()
    .with_handler(MyHandler)
    .with_agent_runtime(MyAgent, is_default=True)
    .with_rest_api(CustomRestApi)
    .build()
)

# With configuration
app = (
    AppBuilder(
        settings_files=["settings.toml", "secrets.toml"],
        root_path="."
    )
    .with_handler(MyHandler)
    .build()
)

# Run app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

## Next Steps

Now that you understand the App Builder:

1. **[Create Handlers](handlers.md)** - Build event processors
2. **[Build LLM Agents](llm-agents.md)** - Add AI capabilities
3. **[Testing Guide](testing.md)** - Test your application

---

**Next:** [Creating Handlers](handlers.md) →
