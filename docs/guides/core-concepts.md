# Core Concepts

**Time to complete:** 10 minutes  
**Difficulty:** Beginner

This guide explains the key concepts you need to understand to work with the Agent Blueprint.

## 1. Events

**What:** Messages that trigger processing

**Example:**
```json
{
  "type": "invoice.created",
  "source": "invoice-service",
  "id": "123",
  "data": {"invoice_id": "INV-001"}
}
```

**Key Points:**
- Events use CloudEvent format (industry standard)
- Events contain metadata (type, source, id, time)
- Events trigger handler chains

## 2. Handlers

**What:** Components that process events

**Think of it like:** Workers on an assembly line

```
Event → Handler 1 → Handler 2 → Handler 3 → Result
         (Check)     (Enrich)     (Process)
```

**Key Points:**
- Each handler does one thing
- Handlers run in priority order (10, 20, 30...)
- Handlers can pass to next or return result

**Example:**
```python
class ValidationHandler(EventHandler):
    priority = 10  # Runs first
    
    async def _can_handle(self, event, context):
        return event.type == "invoice.created"
    
    async def _handle(self, event, context):
        if not valid:
            return {"error": "Invalid"}
        
        context["validated"] = True
        return None  # Continue to next handler
```

## 3. Context

**What:** Shared dictionary between handlers

**Think of it like:** A whiteboard where handlers leave notes

```python
# Handler 1 writes
context["validated"] = True
context["data"] = {...}

# Handler 2 reads
if context.get("validated"):
    data = context["data"]
```

**Key Points:**
- Context is shared across all handlers
- Use it to pass data between handlers
- Don't create new context dict (modify existing)

## 4. Chain of Responsibility

**What:** Design pattern where handlers form a chain

**How it works:**
1. Event arrives
2. Handler 1 checks if it can handle
3. If yes, processes and either:
   - Returns result (stops chain)
   - Returns None (continues to next)
4. Repeat for Handler 2, 3, etc.

**Visual:**
```
┌─────────────┐
│   Event     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Handler 1  │ Can handle? Yes → Process → Return None
└──────┬──────┘                                ↓
       │                                       │
       ▼                                       │
┌─────────────┐                               │
│  Handler 2  │ Can handle? No → Skip ────────┤
└──────┬──────┘                               │
       │                                       │
       ▼                                       │
┌─────────────┐                               │
│  Handler 3  │ Can handle? Yes → Process → Return Result
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Result    │
└─────────────┘
```

## 5. Template Method Pattern

**What:** Base class defines workflow, you fill in details

**Example:**
```python
# Base class (framework provides)
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
        # Just business logic
        return {"status": "success"}
```

**Key Points:**
- You override `_handle()`, not `handle()`
- Framework handles tracing, logging, etc.
- You focus on business logic only

## 6. Agent Runtime

**What:** Wrapper around AI model (GPT-4, etc.)

**Purpose:**
- Loads prompts
- Provides tools to AI
- Handles AI responses
- Returns structured data

**Example:**
```python
class InvoiceAgent(BaseAgent):
    def _get_prompt_name(self):
        return "invoice_processor.txt"
    
    def _get_tools(self):
        return [calculate_invoice, lookup_customer]
    
    def _get_result_type(self):
        return InvoiceAnalysisOutput
```

## 7. Tools

**What:** Functions the AI can call

**Example:**
```python
def calculate_invoice(invoice: InvoiceInput) -> InvoiceAnalysisOutput:
    """Calculate invoice totals."""
    total = sum(item.quantity * item.price for item in invoice.items)
    return InvoiceAnalysisOutput(total=total)
```

**Key Points:**
- Tools are regular Python functions
- Use Pydantic models for inputs/outputs
- AI decides when to call tools
- Tools should be fast and focused

## 8. Pydantic Models

**What:** Data models with validation

**Example:**
```python
class Invoice(BaseModel):
    invoice_id: str = Field(..., min_length=1)
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(..., regex=r"^[A-Z]{3}$")
```

**Benefits:**
- Automatic validation
- Type safety
- Self-documenting
- Easy JSON conversion

## 9. Configuration

**What:** Settings for your application

**Layers:**
```
settings.toml (defaults)
    ↓ overridden by
secrets.toml (sensitive)
    ↓ overridden by
Environment variables (runtime)
```

**Example:**
```toml
# settings.toml
[default]
app_name = "invoice-processor"
log_level = "INFO"

# secrets.toml
[default]
ai_model_api_key = "sk-key"
```

## 10. Observability

**What:** Monitoring and debugging tools

**Three Pillars:**

**Tracing** - See request flow
```
process_event
  ├─ handler.ValidationHandler
  ├─ handler.AgentInvokerHandler
  └─ agent.InvoiceAgent
      └─ tool.calculate_invoice
```

**Logging** - Record events
```python
logger.info("Processing invoice %s", invoice_id)
```

**Metrics** - Health checks
```
GET /actuators/health
```

## Key Principles

### 1. Separation of Concerns

**Base Framework** - Infrastructure (don't modify)
**Custom Code** - Business logic (you modify)

### 2. Stateless Design

Don't store state in handlers:

✅ **Good:**
```python
async def _handle(self, event, context):
    data = context.get("data")  # From context
    result = self.process(data)
    context["result"] = result  # To context
```

❌ **Bad:**
```python
def __init__(self):
    self.data = None  # Instance state!

async def _handle(self, event, context):
    self.data = event.data  # Don't do this!
```

### 3. Single Responsibility

Each handler does one thing:

✅ **Good:**
- ValidationHandler - validates
- EnrichmentHandler - enriches
- AgentInvokerHandler - invokes agent

❌ **Bad:**
- ProcessingHandler - validates, enriches, and processes

### 4. Fail Fast

Validate early, fail fast:

```python
async def _handle(self, event, context):
    # Validate first
    if not event.data:
        return {"error": "No data"}
    
    if not event.data.get("invoice_id"):
        return {"error": "Missing invoice_id"}
    
    # Then process
    result = await self.process(event.data)
    return result
```

## Common Patterns

### Pattern 1: Validation → Enrichment → Processing

```python
# Priority 10
ValidationHandler - Check if valid
    ↓
# Priority 20
EnrichmentHandler - Add customer data
    ↓
# Priority 30
AgentInvokerHandler - Trigger AI
```

### Pattern 2: Early Return

```python
async def _handle(self, event, context):
    # Handle simple cases immediately
    if event.data.get("type") == "simple":
        return {"status": "success"}
    
    # Complex cases continue
    context["needs_processing"] = True
    return None
```

### Pattern 3: Conditional Processing

```python
async def _can_handle(self, event, context):
    # Only handle if conditions met
    return (
        event.type == "invoice.created" and
        context.get("validated") is True and
        event.data.get("amount", 0) > 1000
    )
```

## Mental Models

### Think of Handlers as Filters

```
All Events
    ↓
[ValidationHandler] ← Filters invalid events
    ↓
Valid Events
    ↓
[EnrichmentHandler] ← Adds data
    ↓
Enriched Events
    ↓
[AgentInvokerHandler] ← Triggers AI
    ↓
Processed Events
```

### Think of Context as a Notebook

```
Handler 1: "I validated this ✓"
Handler 2: "I added customer data"
Handler 3: "I need the agent to process this"
Agent: "Here's the result"
```

### Think of Tools as Calculator Buttons

```
AI: "I need to calculate the total"
    ↓ presses button
[calculate_invoice tool]
    ↓ returns result
AI: "The total is 2380.00 EUR"
```

## Quick Reference

| Concept | What | Example |
|---------|------|---------|
| Event | Message that triggers processing | `{"type": "invoice.created"}` |
| Handler | Processes events | `ValidationHandler` |
| Context | Shared data between handlers | `context["validated"] = True` |
| Chain | Handlers in sequence | Handler1 → Handler2 → Handler3 |
| Agent | AI wrapper | `InvoiceAgent` |
| Tool | Function AI can call | `calculate_invoice()` |
| Model | Data with validation | `class Invoice(BaseModel)` |

## Next Steps

Now that you understand the concepts:

1. **[Creating Handlers](handlers.md)** - Build event processors
2. **[Building LLM Agents](llm-agents.md)** - Add AI capabilities
3. **[Architecture Overview](architecture.md)** - Deep dive into system design

---

**Next:** [Creating Handlers](handlers.md) →
