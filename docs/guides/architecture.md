# Architecture Overview

**Time to complete:** 20 minutes  
**Difficulty:** Intermediate

This guide explains how the Agent Blueprint works and how all the pieces fit together.

## The Big Picture

The Agent Blueprint is a **microservice framework** for building **AI-powered agents** that process events.

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Blueprint                       │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐     │
│  │   API    │───▶│ Handlers │───▶│  AI Agent    │     │
│  │ Endpoints│    │  Chain   │    │ (Optional)   │     │
│  └──────────┘    └──────────┘    └──────────────┘     │
│                                                          │
│  ┌──────────────────────────────────────────────┐      │
│  │         Base Framework (Don't Modify)        │      │
│  │  - Event processing  - Health checks         │      │
│  │  - Tracing          - Configuration          │      │
│  └──────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────┘
```

## Core Concepts

### 1. Separation of Concerns

The framework is split into two parts:

**Base Framework** (`base/`)
- Provides infrastructure (API, tracing, config)
- You **don't modify** this
- Handles cross-cutting concerns

**Custom Implementation** (`custom/`)
- Your business logic
- Handlers, agents, tools
- You **modify** this

### 2. Event-Driven Architecture

Everything is triggered by **events**:

```
Event → Handler Chain → (Optional) AI Agent → Result
```

**Example flow:**
1. Invoice uploaded → `invoice.created` event
2. ValidationHandler checks if valid
3. EnrichmentHandler adds customer data
4. AgentInvokerHandler triggers AI
5. AI extracts data and calls tools
6. Result published back

### 3. Chain of Responsibility Pattern

Handlers process events in **priority order**:

```python
# Priority 10 - runs first
ValidationHandler
    ↓ (passes to next)
# Priority 20
EnrichmentHandler
    ↓ (passes to next)
# Priority 30 - runs last
AgentInvokerHandler
```

Each handler can:
- **Process** and return result (stops chain)
- **Process** and pass to next (continues chain)
- **Skip** if it can't handle (continues chain)

## System Components

### Component Registry

**What:** Central storage for all components  
**Location:** `base/src/registry/component_registry.py`

**Responsibilities:**
- Store handlers (sorted by priority)
- Store agent runtimes
- Provide component lookup

**Does NOT:**
- Execute business logic
- Process events
- Make decisions

### Processing Service

**What:** Orchestrates event processing  
**Location:** `base/src/services/processing_service.py`

**Responsibilities:**
- Execute handler chain
- Invoke agent runtime when needed
- Manage context between handlers
- Handle errors and logging

### Event Handler (Base Class)

**What:** Template for custom handlers  
**Location:** `base/src/agent/event_handler.py`

**Pattern:** Chain of Responsibility + Template Method

**Methods:**
- `_can_handle(event, context)` → Should I process this?
- `_handle(event, context)` → Process the event

### Base Agent

**What:** Template for AI agents  
**Location:** `base/src/agent/base_agent.py`

**Methods:**
- `_get_prompt_name()` → Prompt file name
- `_get_tools()` → Tools for AI
- `_get_processing_context_type()` → Input model
- `_get_result_type()` → Output model

## Request Flow

### REST Request Flow

```
1. Client sends POST to /api/process-resource
   ↓
2. RestApi validates payload
   ↓
3. Converts to CloudEvent format
   ↓
4. ProcessingService.process_event()
   ↓
5. Handler chain executes (priority order)
   ↓
6. If context["use_agent"] = True:
   ↓
7. ProcessingService invokes agent runtime
   ↓
8. Agent calls LLM with tools
   ↓
9. LLM returns structured output
   ↓
10. Response returned to client
```

### Event Processing Flow

```
1. RabbitMQ receives message
   ↓
2. Dapr pulls message
   ↓
3. Dapr POSTs to /events/process
   ↓
4. EventApi receives CloudEvent
   ↓
5. ProcessingService.process_event()
   ↓
6. Handler chain executes
   ↓
7. (Optional) Agent invoked
   ↓
8. Result published back to RabbitMQ
   ↓
9. Dapr ACKs message
```

## Data Flow

### Context Dictionary

The `context` dict is shared between handlers:

```python
# Handler 1 writes
context["validated"] = True
context["invoice_data"] = {...}

# Handler 2 reads
if context.get("validated"):
    data = context["invoice_data"]
    # process...

# Handler 3 triggers agent
context["use_agent"] = True
context["agent_input"] = data
```

**Think of context as a shared whiteboard** where handlers leave notes for each other.

### CloudEvent Format

All events use CloudEvent format:

```json
{
  "specversion": "1.0",
  "type": "invoice.created",
  "source": "invoice-service",
  "id": "unique-id-123",
  "time": "2025-10-10T10:00:00Z",
  "datacontenttype": "application/json",
  "data": {
    "invoice_id": "INV-001",
    "amount": 100.00
  }
}
```

**Why CloudEvents?**
- Industry standard
- Works with Dapr, Kafka, etc.
- Includes metadata (id, time, source)

## Design Patterns

### 1. Template Method Pattern

Base classes define the workflow, you fill in the details:

```python
# Base class (framework)
class EventHandler:
    async def handle(self, event, context):
        # Framework adds tracing
        with tracer.start_span("handler"):
            return await self._handle(event, context)
    
    @abstractmethod
    async def _handle(self, event, context):
        """You implement this"""
        pass

# Your class
class MyHandler(EventHandler):
    async def _handle(self, event, context):
        # Just business logic, no tracing needed
        return {"status": "success"}
```

### 2. Chain of Responsibility

Handlers form a chain:

```python
class ValidationHandler(EventHandler):
    priority = 10
    
    async def _handle(self, event, context):
        if not valid:
            return {"error": "Invalid"}  # Stops chain
        
        context["validated"] = True
        return None  # Continue to next handler

class ProcessingHandler(EventHandler):
    priority = 20
    
    async def _handle(self, event, context):
        if not context.get("validated"):
            return None  # Skip
        
        # Process...
        return result  # Stops chain
```

### 3. Dependency Injection

Components receive dependencies via constructor:

```python
class MyHandler(EventHandler):
    def __init__(self, database, cache):
        super().__init__("MyHandler", priority=20)
        self.database = database
        self.cache = cache
```

### 4. Builder Pattern

App Builder uses fluent interface:

```python
app = (
    AppBuilder()
    .with_handler(Handler1)
    .with_handler(Handler2)
    .with_agent_runtime(MyAgent)
    .build()
)
```

## Observability

### OpenTelemetry Tracing

Every component is automatically traced:

```
Span: process_event
  ├─ Span: handler.ValidationHandler.can_handle
  ├─ Span: handler.ValidationHandler.handle
  ├─ Span: handler.AgentInvokerHandler.can_handle
  ├─ Span: handler.AgentInvokerHandler.handle
  └─ Span: agent.InvoiceAgent.run
      └─ Span: tool.calculate_invoice
```

**You don't need to add tracing** - it's automatic!

### Logging

Use lazy % formatting:

```python
# Good
logger.info("Processing invoice %s", invoice_id)

# Bad
logger.info(f"Processing invoice {invoice_id}")
```

**Why?** Defers string interpolation until needed.

### Health Checks

Built-in endpoints:

- `/actuators/health` - Overall health
- `/actuators/health/liveness` - Is app running?
- `/actuators/health/readiness` - Is app ready?

## Configuration Management

### Configuration Layers

```
1. settings.toml (defaults)
   ↓ overridden by
2. secrets.toml (sensitive data)
   ↓ overridden by
3. Environment variables (runtime)
```

### Example

**settings.toml:**
```toml
[default]
app_name = "invoice-processor"
log_level = "INFO"
```

**secrets.toml:**
```toml
[default]
ai_model_api_key = "sk-key"
```

**Environment:**
```bash
export LOG_LEVEL="DEBUG"  # Overrides settings.toml
```

**Result:**
- `app_name` = "invoice-processor" (from settings.toml)
- `log_level` = "DEBUG" (from environment)
- `ai_model_api_key` = "sk-key" (from secrets.toml)

## Error Handling

### Handler Errors

```python
async def _handle(self, event, context):
    try:
        result = await self.process(event.data)
        return result
    
    except ValidationError as e:
        # Return error, don't raise
        return {"status": "error", "message": str(e)}
    
    except RetryableError as e:
        # Raise to trigger retry
        raise
    
    except Exception as e:
        # Log and raise
        logger.exception("Unexpected error: %s", e)
        raise
```

### Agent Errors

```python
async def process_request(self, context, instruction):
    try:
        result = await self.agent.run(instruction)
        return self._handle_agent_response(result)
    
    except Exception as e:
        logger.exception("Agent failed: %s", e)
        # Return error output instead of raising
        return ErrorOutput(
            status="error",
            message=str(e)
        )
```

## Scalability Considerations

### Horizontal Scaling

Run multiple instances:

```bash
# Instance 1
uvicorn custom.src.main:app --port 8001

# Instance 2
uvicorn custom.src.main:app --port 8002

# Instance 3
uvicorn custom.src.main:app --port 8003
```

Load balancer distributes requests.

### Message Processing

Each instance processes messages independently:

```
RabbitMQ Queue
    ├─ Instance 1 (processes message 1)
    ├─ Instance 2 (processes message 2)
    └─ Instance 3 (processes message 3)
```

### Stateless Design

**Important:** Keep handlers stateless!

✅ **Good:**
```python
async def _handle(self, event, context):
    # All state in context
    data = context.get("data")
    result = self.process(data)
    context["result"] = result
    return None
```

❌ **Bad:**
```python
def __init__(self):
    self.data = None  # Instance state!

async def _handle(self, event, context):
    self.data = event.data  # Don't do this!
```

## Security Considerations

### Secrets Management

Never commit secrets:

```bash
# .gitignore already includes:
secrets.toml
.env
*.key
```

Use environment variables in production:

```bash
export AI_MODEL_API_KEY="sk-prod-key"
export DATABASE_PASSWORD="secret"
```

### Input Validation

Always validate inputs:

```python
class InvoiceInput(BaseModel):
    invoice_id: str = Field(..., min_length=1, max_length=50)
    amount: Decimal = Field(..., gt=0, le=1000000)
    currency: str = Field(..., regex=r"^[A-Z]{3}$")
```

### API Security

Add authentication middleware:

```python
from fastapi import Security, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.post("/api/process")
async def process(
    payload: dict,
    token: str = Security(security)
):
    if not validate_token(token):
        raise HTTPException(401, "Invalid token")
    # Process...
```

## Performance Tips

### 1. Use Async/Await

```python
# Good - parallel execution
customer, products = await asyncio.gather(
    fetch_customer(id),
    fetch_products(ids)
)

# Bad - sequential execution
customer = await fetch_customer(id)
products = await fetch_products(ids)
```

### 2. Cache Expensive Operations

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def lookup_customer(customer_id: str):
    # Cached for repeated lookups
    return fetch_customer(customer_id)
```

### 3. Limit Handler Complexity

Keep handlers simple and fast:
- Don't make many API calls
- Avoid heavy computations
- Use async for I/O

### 4. Monitor Performance

```python
import time

async def _handle(self, event, context):
    start = time.time()
    
    result = await self.process(event.data)
    
    duration = time.time() - start
    logger.info("Processing took %.2f seconds", duration)
    
    return result
```

## Testing Strategy

### Unit Tests

Test components in isolation:

```python
def test_handler():
    handler = MyHandler()
    event = CloudEvent(...)
    context = {}
    
    result = await handler._handle(event, context)
    
    assert result["status"] == "success"
```

### Integration Tests

Test the full flow:

```python
def test_full_flow():
    client = TestClient(app)
    
    response = client.post("/api/process", json={...})
    
    assert response.status_code == 200
    assert response.json()["status"] == "success"
```

### Mock External Services

```python
@pytest.fixture
def mock_llm(monkeypatch):
    async def mock_run(*args, **kwargs):
        return MockResult(data={"status": "success"})
    
    monkeypatch.setattr("pydantic_ai.Agent.run", mock_run)
```

## Common Patterns

### Pattern 1: Thin vs Fat Events

**Thin Event:** Just an ID
```json
{
  "type": "asset.check",
  "data": {"asset_id": "12345"}
}
```

Handler fetches full data from Data Gateway.

**Fat Event:** Full data
```json
{
  "type": "asset.check",
  "data": {
    "asset_id": "12345",
    "name": "Server-01",
    "backup_status": "pending"
  }
}
```

Handler uses data directly.

### Pattern 2: Idempotent Processing

Process same event multiple times safely:

```python
async def _handle(self, event, context):
    event_id = event.id
    
    # Check if already processed
    if await self.is_processed(event_id):
        logger.info("Event %s already processed", event_id)
        return {"status": "duplicate"}
    
    # Process
    result = await self.process(event.data)
    
    # Mark as processed
    await self.mark_processed(event_id)
    
    return result
```

### Pattern 3: Dead Letter Queue

Failed messages go to DLQ:

```yaml
# Dapr subscription
deadLetterTopic: invoice.events.dlq
```

Monitor and replay:

```python
async def replay_dlq():
    """Replay messages from DLQ."""
    messages = await fetch_dlq_messages()
    
    for msg in messages:
        try:
            await process_event(msg)
            await delete_from_dlq(msg.id)
        except Exception as e:
            logger.error("Replay failed: %s", e)
```

## Architecture Decisions

### Why FastAPI?

- **Fast** - Built on Starlette and Pydantic
- **Modern** - Async/await support
- **Type-safe** - Automatic validation
- **Documented** - Auto-generated OpenAPI docs

### Why Pydantic AI?

- **Type-safe** - Pydantic models for I/O
- **Flexible** - Works with OpenAI, Anthropic, vLLM
- **Structured** - Returns validated data
- **Testable** - Easy to mock

### Why Dapr?

- **Portable** - Switch message brokers easily
- **Resilient** - Built-in retries and DLQ
- **Observable** - Automatic tracing
- **Standard** - CloudEvents format

### Why Chain of Responsibility?

- **Flexible** - Add/remove handlers easily
- **Testable** - Test handlers independently
- **Reusable** - Same handler in different contexts
- **Clear** - Each handler has one job

## Next Steps

Now that you understand the architecture:

1. **[Testing Guide](testing.md)** - Test your agents
2. **[Deployment Guide](deployment.md)** - Deploy to production
3. **[Troubleshooting](troubleshooting.md)** - Fix common issues

## Quick Reference

**Key Components:**
- `ComponentRegistry` - Stores handlers and runtimes
- `ProcessingService` - Orchestrates processing
- `EventHandler` - Base class for handlers
- `BaseAgent` - Base class for AI agents

**Request Flow:**
```
API → ProcessingService → Handler Chain → (Agent) → Result
```

**Context Usage:**
```python
context["use_agent"] = True  # Trigger agent
context["data"] = {...}      # Share data
```

**Configuration:**
```
settings.toml → secrets.toml → Environment Variables
```

---

**Next:** [Testing Guide](testing.md) →
