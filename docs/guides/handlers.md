# Creating Event Handlers

**Time to complete:** 20 minutes  
**Difficulty:** Intermediate

This guide teaches you how to create event handlers using the Chain of Responsibility pattern.

## What Are Handlers?

**Handlers** are components that process events. Think of them as workers in an assembly line:

```
Event → Handler 1 → Handler 2 → Handler 3 → Result
         (Check)     (Enrich)     (Process)
```

Each handler:
1. **Checks** if it can handle the event
2. **Processes** the event if it can
3. **Passes** to the next handler or returns a result

## Why Use Handlers?

**Benefits:**
- **Separation of Concerns** - Each handler does one thing well
- **Flexibility** - Add/remove handlers without changing other code
- **Testability** - Test each handler independently
- **Reusability** - Use the same handler in different contexts

**Example:** Processing an invoice might involve:
1. **ValidationHandler** - Check if invoice is valid
2. **EnrichmentHandler** - Add customer data
3. **AgentInvokerHandler** - Send to AI for analysis
4. **PublisherHandler** - Publish results

## The Chain of Responsibility Pattern

### How It Works

```python
# Handler 1
if can_handle(event):
    result = handle(event)
    if result:
        return result  # Stop chain
    # else: continue to next handler

# Handler 2
if can_handle(event):
    result = handle(event)
    if result:
        return result
    # else: continue

# And so on...
```

### Priority Order

Handlers run in **priority order** (lower numbers first):

```python
ValidationHandler(priority=10)      # Runs first
EnrichmentHandler(priority=20)      # Runs second
AgentInvokerHandler(priority=30)    # Runs third
```

## Creating Your First Handler

### Step 1: Understand the Base Class

All handlers extend `EventHandler`:

```python
from base.src.agent import EventHandler
from base.src.models.events import CloudEvent

class MyHandler(EventHandler):
    def __init__(self):
        super().__init__(
            name="MyHandler",      # Human-readable name
            priority=20            # Execution order
        )
    
    async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
        """Should this handler process this event?"""
        # Return True if you want to handle it
        pass
    
    async def handle_event(self, event: CloudEvent, context: dict):
        """Process the event."""
        # Your logic here
        # Return result or None to continue chain
        pass
    
    def get_runtime_name(self, event: CloudEvent, context: dict) -> str | None:
        """Return the agent runtime to use (optional)."""
        # Return runtime name, "" for default, or None to skip agent
        return None
```

**Key Methods:**

| Method | Purpose | Return |
|--------|---------|--------|
| `can_handle_event()` | Check if handler should process | `True` or `False` |
| `handle_event()` | Process the event | Result or `None` |
| `get_runtime_name()` | Specify agent runtime (optional) | Runtime name, `""`, or `None` |

### Step 2: Implement _can_handle()

This method decides if your handler should process the event.

**Example 1: Check event type**
```python
async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
    """Handle invoice events only."""
    return event.type == "invoice.created"
```

**Example 2: Check payload data**
```python
async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
    """Handle events with 'urgent' flag."""
    if not event.data:
        return False
    return event.data.get("priority") == "urgent"
```

**Example 3: Check context**
```python
async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
    """Handle if previous handler validated the event."""
    return context.get("validated") is True
```

**Example 4: Complex logic**
```python
async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
    """Handle invoice events with amount > 1000."""
    if event.type != "invoice.created":
        return False
    
    amount = event.data.get("amount", 0)
    return amount > 1000
```

### Step 3: Implement _handle()

This method processes the event.

**Example 1: Simple processing**
```python
async def handle_event(self, event: CloudEvent, context: dict):
    """Log and enrich the event."""
    logger.info("Processing event: %s", event.id)
    
    # Add data to context for next handlers
    context["processed_by"] = self.name
    context["timestamp"] = datetime.now()
    
    # Return None to continue chain
    return None
```

**Example 2: Return result (stops chain)**
```python
async def handle_event(self, event: CloudEvent, context: dict):
    """Validate invoice and return result."""
    invoice = event.data
    
    if not invoice.get("invoice_id"):
        return {
            "status": "error",
            "message": "Missing invoice_id"
        }
    
    # Validation passed
    context["validated"] = True
    return None  # Continue to next handler
```

**Example 3: Invoke agent**
```python
async def handle_event(self, event: CloudEvent, context: dict):
    """Trigger AI agent processing."""
    logger.info("Invoking agent for event: %s", event.id)
    
    # Set flag for ProcessingService to invoke agent
    context["use_agent"] = True
    context["agent_name"] = "InvoiceAgent"
    context["invoice_data"] = event.data
    
    return None  # Let ProcessingService handle agent invocation
```

## Complete Handler Examples

### Example 1: Validation Handler

```python
class InvoiceValidationHandler(EventHandler):
    """Validates invoice data before processing."""
    
    def __init__(self):
        super().__init__("InvoiceValidationHandler", priority=10)
    
    async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
        """Handle invoice events."""
        return event.type == "invoice.created"
    
    async def handle_event(self, event: CloudEvent, context: dict):
        """Validate invoice data."""
        invoice = event.data
        
        # Check required fields
        required_fields = ["invoice_id", "amount", "currency"]
        missing = [f for f in required_fields if f not in invoice]
        
        if missing:
            logger.error("Missing required fields: %s", missing)
            return {
                "status": "error",
                "message": f"Missing fields: {', '.join(missing)}"
            }
        
        # Validate amount
        if invoice["amount"] <= 0:
            return {
                "status": "error",
                "message": "Amount must be positive"
            }
        
        # Validation passed
        logger.info("Invoice %s validated successfully", invoice["invoice_id"])
        context["validated"] = True
        context["invoice"] = invoice
        
        return None  # Continue to next handler
```

### Example 2: Enrichment Handler

```python
class CustomerEnrichmentHandler(EventHandler):
    """Enriches invoice with customer data."""
    
    def __init__(self):
        super().__init__("CustomerEnrichmentHandler", priority=20)
    
    async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
        """Handle validated invoices."""
        return context.get("validated") is True
    
    async def handle_event(self, event: CloudEvent, context: dict):
        """Add customer information."""
        invoice = context["invoice"]
        customer_id = invoice.get("customer_id")
        
        if not customer_id:
            logger.warning("No customer_id, skipping enrichment")
            return None
        
        # Fetch customer data (example)
        customer = await self._fetch_customer(customer_id)
        
        # Add to context
        context["customer"] = customer
        context["enriched"] = True
        
        logger.info("Enriched invoice with customer: %s", customer.get("name"))
        return None
```

### Example 3: Agent Invoker Handler

```python
class AgentInvokerHandler(EventHandler):
    """Triggers AI agent for complex processing."""
    
    def __init__(self):
        super().__init__("AgentInvokerHandler", priority=30)
    
    async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
        """Handle enriched invoices."""
        return context.get("enriched") is True
    
    async def handle_event(self, event: CloudEvent, context: dict):
        """Invoke AI agent."""
        invoice = context["invoice"]
        customer = context.get("customer", {})
        
        logger.info("Invoking agent for invoice: %s", invoice["invoice_id"])
        
        # Prepare data for agent
        context["use_agent"] = True
        context["agent_name"] = "InvoiceAnalysisAgent"
        context["agent_input"] = {
            "invoice": invoice,
            "customer": customer,
            "metadata": {
                "event_id": event.id,
                "event_type": event.type
            }
        }
        
        return None  # ProcessingService will invoke agent
```

## Using Context

The `context` dictionary is shared between handlers. Use it to pass data:

### Writing to Context

```python
async def handle_event(self, event: CloudEvent, context: dict):
    # Add simple values
    context["validated"] = True
    context["timestamp"] = datetime.now()
    
    # Add complex objects
    context["invoice_data"] = {
        "id": "INV-001",
        "amount": 100.00
    }
    
    # Add lists
    context["processed_by"] = context.get("processed_by", [])
    context["processed_by"].append(self.name)
    
    return None
```

### Reading from Context

```python
async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
    # Check if key exists
    if "validated" not in context:
        return False
    
    # Get with default
    priority = context.get("priority", "normal")
    
    # Check multiple conditions
    return (
        context.get("validated") is True and
        context.get("enriched") is True
    )
```

## Registering Handlers

### Step 1: Add to handlers.py

In `custom/src/agent/handlers.py`:

```python
# Import base class
from base.src.agent import EventHandler
from base.src.models.events import CloudEvent

# Your handler classes
class MyHandler(EventHandler):
    # ... implementation ...
    pass

class AnotherHandler(EventHandler):
    # ... implementation ...
    pass

# Export all handlers
all_handlers = [
    MyHandler(),
    AnotherHandler(),
]
```

### Step 2: Register in main.py

In `custom/src/main.py`:

```python
from .agent.handlers import MyHandler, AnotherHandler

app = (
    AppBuilder()
    .with_handler(MyHandler)
    .with_handler(AnotherHandler)
    .with_agent_runtime(AgentRuntime, is_default=True)
    .build()
)
```

## Handler Patterns

### Pattern 1: Early Return

Stop the chain if processing is complete:

```python
async def handle_event(self, event: CloudEvent, context: dict):
    # Process simple cases immediately
    if event.data.get("type") == "simple":
        return {
            "status": "success",
            "message": "Simple case handled"
        }
    
    # Complex cases continue to next handler
    context["needs_complex_processing"] = True
    return None
```

### Pattern 2: Conditional Processing

Only process if conditions are met:

```python
async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
    # Multiple conditions
    return (
        event.type == "invoice.created" and
        context.get("validated") is True and
        event.data.get("amount", 0) > 1000
    )
```

### Pattern 3: Error Handling

Handle errors gracefully:

```python
async def handle_event(self, event: CloudEvent, context: dict):
    try:
        result = await self.process_invoice(event.data)
        context["result"] = result
        return None
    
    except ValidationError as e:
        logger.error("Validation failed: %s", e)
        return {
            "status": "error",
            "message": str(e)
        }
    
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        # Re-raise to trigger retry
        raise
```

### Pattern 4: Async Operations

Perform async operations:

```python
async def handle_event(self, event: CloudEvent, context: dict):
    # Parallel operations
    customer, products = await asyncio.gather(
        self._fetch_customer(event.data["customer_id"]),
        self._fetch_products(event.data["product_ids"])
    )
    
    context["customer"] = customer
    context["products"] = products
    
    return None
```

## Testing Handlers

### Unit Test Example

```python
import pytest
from custom.src.agent.handlers import InvoiceValidationHandler
from base.src.models.events import CloudEvent

@pytest.mark.asyncio
async def test_validation_handler_success():
    """Test successful validation."""
    handler = InvoiceValidationHandler()
    
    event = CloudEvent(
        type="invoice.created",
        data={
            "invoice_id": "INV-001",
            "amount": 100.00,
            "currency": "EUR"
        }
    )
    context = {}
    
    # Check if handler can handle
    assert await handler.can_handle_event(event, context) is True
    
    # Process event
    result = await handler.handle_event(event, context)
    
    # Should continue chain (return None)
    assert result is None
    
    # Should set validated flag
    assert context["validated"] is True

@pytest.mark.asyncio
async def test_validation_handler_missing_field():
    """Test validation with missing field."""
    handler = InvoiceValidationHandler()
    
    event = CloudEvent(
        type="invoice.created",
        data={
            "amount": 100.00
            # Missing invoice_id
        }
    )
    context = {}
    
    # Process event
    result = await handler.handle_event(event, context)
    
    # Should return error
    assert result["status"] == "error"
    assert "invoice_id" in result["message"]
```

## Best Practices

### 1. Single Responsibility

Each handler should do one thing:

✅ **Good:**
```python
class ValidationHandler(EventHandler):
    """Validates invoice data."""
    pass

class EnrichmentHandler(EventHandler):
    """Enriches with customer data."""
    pass
```

❌ **Bad:**
```python
class InvoiceHandler(EventHandler):
    """Validates, enriches, and processes invoices."""
    pass
```

### 2. Use Descriptive Names

```python
# Good names
InvoiceValidationHandler
CustomerEnrichmentHandler
AgentInvokerHandler

# Bad names
Handler1
ProcessHandler
MyHandler
```

### 3. Log Important Actions

```python
async def handle_event(self, event: CloudEvent, context: dict):
    logger.info("Processing invoice: %s", event.data["invoice_id"])
    
    result = await self.process(event.data)
    
    logger.info("Invoice processed successfully: %s", result["status"])
    return None
```

### 4. Use Type Hints

```python
from typing import Any, Optional

async def handle_event(
    self, 
    event: CloudEvent, 
    context: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Process the event."""
    pass
```

### 5. Handle Edge Cases

```python
async def handle_event(self, event: CloudEvent, context: dict):
    # Check for None
    if not event.data:
        logger.warning("Empty event data")
        return None
    
    # Check for required fields
    invoice_id = event.data.get("invoice_id")
    if not invoice_id:
        return {"status": "error", "message": "Missing invoice_id"}
    
    # Process...
```

## Common Patterns

### Pattern: Feature Flags

```python
async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
    """Only handle if feature is enabled."""
    if not self.config.get("enable_ai_processing"):
        return False
    
    return event.type == "invoice.created"
```

### Pattern: Rate Limiting

```python
async def handle_event(self, event: CloudEvent, context: dict):
    """Process with rate limiting."""
    if not await self.rate_limiter.acquire():
        logger.warning("Rate limit exceeded, requeueing")
        raise RateLimitError("Too many requests")
    
    return await self.process(event.data)
```

### Pattern: Caching

```python
async def handle_event(self, event: CloudEvent, context: dict):
    """Enrich with cached customer data."""
    customer_id = event.data["customer_id"]
    
    # Check cache
    customer = await self.cache.get(f"customer:{customer_id}")
    
    if not customer:
        # Fetch and cache
        customer = await self.fetch_customer(customer_id)
        await self.cache.set(f"customer:{customer_id}", customer, ttl=3600)
    
    context["customer"] = customer
    return None
```

## Troubleshooting

### Handler Not Running

**Check:**
1. Is handler registered in `main.py`?
2. Does `_can_handle()` return `True`?
3. Is priority correct?

**Debug:**
```python
async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
    result = event.type == "invoice.created"
    logger.debug("Can handle? %s (event.type=%s)", result, event.type)
    return result
```

### Chain Stops Early

**Cause:** A handler returned a non-None result.

**Solution:** Return `None` to continue:
```python
async def handle_event(self, event: CloudEvent, context: dict):
    # Process
    context["processed"] = True
    
    # Continue chain
    return None  # Not: return {"status": "success"}
```

### Context Not Shared

**Cause:** Creating new context dict.

**Solution:** Modify existing context:
```python
# Good
context["validated"] = True

# Bad
context = {"validated": True}  # Creates new dict!
```

## Next Steps

Now that you understand handlers:

1. **[Build LLM Agents](llm-agents.md)** - Add AI capabilities
2. **[Testing Guide](testing.md)** - Test your handlers
3. **[Architecture Overview](architecture.md)** - Understand the full system

## Quick Reference

```python
# Basic handler structure
class MyHandler(EventHandler):
    def __init__(self):
        super().__init__("MyHandler", priority=20)
    
    async def can_handle_event(self, event, context):
        return True  # Your condition
    
    async def handle_event(self, event, context):
        # Your logic
        return None  # Continue chain

# Register handler
app = AppBuilder().with_handler(MyHandler).build()

# Test handler
handler = MyHandler()
can_handle = await handler.can_handle_event(event, context)
result = await handler.handle_event(event, context)
```

## Selecting Agent Runtimes

Handlers can specify which agent runtime should process an event using the `get_runtime_name()` method.

### Runtime Selection Method

```python
def get_runtime_name(self, event: CloudEvent, context: dict) -> str | None:
    """Return the name of the agent runtime to use.
    
    Returns:
        - Runtime name (e.g., "invoice_analyzer") for specific runtime
        - Empty string ("") to use default runtime
        - None to skip agent processing entirely
    """
```

### Return Values

| Return Value | Behavior | Use Case |
|--------------|----------|----------|
| `"invoice_analyzer"` | Use named runtime | Route to specialized runtime |
| `"document_classifier"` | Use named runtime | Different specialized runtime |
| `""` (empty string) | Use default runtime | No specific runtime needed |
| `None` | Skip agent processing | Handler fully processes event |

### Example: Route to Specific Runtime

```python
class InvoiceHandler(EventHandler):
    """Routes invoices to the invoice analyzer runtime."""
    
    def __init__(self):
        super().__init__("InvoiceHandler", priority=10)
    
    async def can_handle_event(self, event, context) -> bool:
        return event.data.details.get("action") == "process_invoice"
    
    async def handle_event(self, event, context):
        # Prepare context for agent
        context["invoice_text"] = event.data.invoice_text
        return None  # Let agent process
    
    def get_runtime_name(self, event, context) -> str:
        """Route to invoice analyzer runtime."""
        return "invoice_analyzer"
```

### Example: Skip Agent Processing

```python
class SimpleProcessorHandler(EventHandler):
    """Processes simple events without an agent."""
    
    async def can_handle_event(self, event, context) -> bool:
        return event.data.details.get("action") == "simple_process"
    
    async def handle_event(self, event, context):
        # Fully process the event
        return {
            "status": "processed",
            "data": self._process_data(event.data)
        }
    
    def get_runtime_name(self, event, context) -> None:
        """No agent needed."""
        return None
```

### Example: Dynamic Runtime Selection

```python
class SmartRoutingHandler(EventHandler):
    """Routes to different runtimes based on document type."""
    
    async def can_handle_event(self, event, context) -> bool:
        return event.data.details.get("action") == "analyze_document"
    
    async def handle_event(self, event, context):
        context["document_text"] = event.data.text
        return None
    
    def get_runtime_name(self, event, context) -> str:
        """Route based on document type."""
        doc_type = event.data.details.get("document_type")
        
        if doc_type == "invoice":
            return "invoice_analyzer"
        elif doc_type == "contract":
            return "contract_analyzer"
        elif doc_type == "email":
            return "email_classifier"
        else:
            return ""  # Use default runtime
```

### Processing Flow

```
1. Event arrives
   ↓
2. Handler chain processes event
   ↓
3. Handler calls handle_event()
   ↓
4. Framework calls get_runtime_name()
   ↓
5. Based on return value:
   - None → Skip agent, use handler result
   - "" → Use default runtime
   - "name" → Use named runtime
   ↓
6. Agent processes (if runtime specified)
   ↓
7. Return final result
```

---

**Next:** [Building LLM Agents](llm-agents.md) →
