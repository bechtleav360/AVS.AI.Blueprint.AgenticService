# Creating Event Handlers

**Time to complete:** 15 minutes  
**Difficulty:** Beginner

This guide shows you how to create event handlers that process events step-by-step.

## What Are Handlers?

**Handlers** process events like workers on an assembly line:

```
Event → Handler 1 → Handler 2 → Handler 3 → Result
         (Validate)   (Enrich)    (Process)
```

Each handler:
1. **Checks** - Can I handle this event?
2. **Processes** - Do my work
3. **Decides** - Stop here or continue to next handler?

## Why Use Handlers?

- **Simple** - Each handler does one job
- **Flexible** - Easy to add or remove handlers
- **Testable** - Test each handler alone
- **Reusable** - Use same handler in different places

## The Chain Pattern

Handlers run in **priority order** (lower number = runs first):

```python
ValidationHandler(priority=10)    # Runs 1st
EnrichmentHandler(priority=20)    # Runs 2nd  
ProcessingHandler(priority=30)    # Runs 3rd
```

**Two ways to control the chain:**

1. **Return a result** → Chain stops, result is returned
2. **Return None** → Chain continues to next handler

## Creating a Handler

### Basic Structure

```python
from base.src.handler import EventHandler
from base.src.models import CloudEvent

class MyHandler(EventHandler):
    def __init__(self):
        super().__init__(
            name="MyHandler",    # Give it a name
            priority=20          # Set when it runs
        )
    
    async def can_handle_event(self, event, context):
        """Should I process this event?"""
        return event.type == "invoice.received"
    
    async def handle_event(self, event, context):
        """Process the event."""
        # Do your work here
        return {"status": "processed"}
```

### Example 1: Simple Validation Handler

This handler validates data and continues to the next handler:

```python
class ValidationHandler(EventHandler):
    def __init__(self):
        super().__init__("ValidationHandler", priority=10)
    
    async def can_handle_event(self, event, context):
        return event.type == "invoice.received"
    
    async def handle_event(self, event, context):
        # Validate the invoice
        if not event.data.get("invoice_id"):
            return {"error": "Missing invoice_id"}
        
        # Add validation flag to context
        context["validated"] = True
        
        # Return None to continue to next handler
        return None
```

### Example 2: Handler That Calls an AI Agent

This handler gets an AI agent and uses it:

```python
class AgentInvokerHandler(EventHandler):
    def __init__(self):
        super().__init__("AgentInvoker", priority=30)
    
    async def can_handle_event(self, event, context):
        # Only process if validated
        return context.get("validated") is True
    
    async def handle_event(self, event, context):
        # Get the AI agent
        agent = self._get_agent("invoice_analyzer")
        
        # Prepare instruction
        instruction = f"Analyze this invoice: {event.data['text']}"
        
        # Run the agent
        result = await agent.run(instruction)
        
        # Return result (stops chain)
        return {
            "status": "success",
            "analysis": result.data
        }
```

### Example 3: Handler with Custom Instruction Prompts

Load instruction prompts from files (can be changed without code changes):

```python
from base.src.agent import PromptLoader

class SmartHandler(EventHandler):
    def __init__(self):
        super().__init__("SmartHandler", priority=20)
    
    async def handle_event(self, event, context):
        # Load instruction from file with variables
        instruction = PromptLoader.load_instruction_prompt(
            "invoice_instruction",     # File: prompts/invoice_instruction.prompt
            self.__class__,
            invoice_text=event.data["text"],
            priority=event.data.get("priority", "normal")
        )
        
        agent = self._get_agent("invoice_analyzer")
        result = await agent.run(instruction)
        
        return {"result": result.data}
```

## Using Context to Share Data

Handlers can add data to `context` for other handlers:

```python
class EnrichmentHandler(EventHandler):
    async def handle_event(self, event, context):
        # Fetch customer data
        customer = await self.get_customer(event.data["customer_id"])
        
        # Add to context for next handlers
        context["customer"] = customer
        context["enriched"] = True
        
        # Continue to next handler
        return None

class ProcessingHandler(EventHandler):
    async def handle_event(self, event, context):
        # Use data from previous handler
        customer = context.get("customer")
        
        return {
            "processed": True,
            "customer_name": customer["name"]
        }
```

## Registering Handlers

Add your handler in `main.py`:

```python
from .handlers import MyHandler

app = (
    AppBuilder(settings_files=settings_files, root_path=project_root)
    .with_handler(MyHandler)        # Add your handler
    .with_handler(AnotherHandler)   # Add more handlers
    .build()
)
```

## Publishing Events from Handlers

Handlers can automatically publish events based on their processing results using the **HandlerResult** pattern.

### Why Publish Events?

When a handler completes processing, you often want to:
- Notify other systems about the result
- Trigger downstream workflows
- Send different events based on success/failure
- Use routing keys for topic-based routing

### The HandlerResult Model

Instead of returning plain dictionaries, return a **HandlerResult** model:

```python
from custom.src.models import HandlerResult

return HandlerResult(
    data={"result": "data"},           # Your result data
    event_type="invoice.validated",    # Event type to publish (optional)
    metadata={"key": "value"}          # Additional metadata
)
```

**Key Features:**
- ✅ **Type-safe** - Pydantic model validation
- ✅ **Automatic publishing** - Set `event_type` and it's published
- ✅ **Optional** - Leave `event_type=None` to skip publishing
- ✅ **Stops chain** - Returning HandlerResult stops the handler chain

### Example: Publishing Different Events Based on Validation

This example shows how to publish three different events based on invoice validation status:

```python
from typing import Optional
from base.src.handler import EventHandler
from base.src.models import CloudEvent
from base.src.agent import PromptLoader
from custom.src.models import HandlerResult, InvoiceAnalysisOutput

class AgentInvokerHandler(EventHandler):
    """Handler that validates invoices and publishes different events."""
    
    def __init__(self):
        super().__init__("AgentInvokerHandler", priority=10)
    
    async def can_handle_event(self, event, context):
        return event.data.get("details", {}).get("action") == "invoke_agent"
    
    async def handle_event(self, event, context) -> Optional[HandlerResult]:
        """Process invoice and publish result event."""
        
        try:
            # Get agent and process
            agent = self._get_agent("invoice_analyzer")
            instruction = PromptLoader.load_instruction_prompt(
                "invoice_instruction",
                self.__class__,
                invoice_text=event.data["invoice_text"]
            )
            
            result = await agent.run(instruction)
            analysis: InvoiceAnalysisOutput = result.data
            
            # Determine which event to publish based on validation status
            if analysis.status.lower() == "valid":
                event_type = "invoice.validated"
                logger.info("Invoice %s is VALID", analysis.invoice_id)
                
            elif analysis.status.lower() in ["invalid", "incomplete"]:
                event_type = "invoice.invalidated"
                logger.warning("Invoice %s is INVALID: %s", 
                             analysis.invoice_id, analysis.notes)
            else:
                # Unknown status - treat as invalid
                event_type = "invoice.invalidated"
            
            # Return structured result with event type for publishing
            return HandlerResult(
                data=analysis.model_dump(),
                event_type=event_type,  # ← Triggers automatic publishing
                metadata={
                    "invoice_id": analysis.invoice_id,
                    "status": analysis.status,
                    "confidence": analysis.confidence,
                },
            )
            
        except Exception as e:
            logger.error("Agent processing failed: %s", str(e), exc_info=True)
            
            # Return error result with error event type
            return HandlerResult(
                data={"error": str(e)},
                event_type="invoice.analysis.error",  # ← Error event
                metadata={"error_type": type(e).__name__},
            )
    
    def get_published_event_types(self):
        """Declare event types this handler can publish."""
        return (
            "invoice.validated",
            "invoice.invalidated",
            "invoice.analysis.error",
        )
```

### Configuring Event Publishing

Map event types to topics in `values.yaml`:

```yaml
eventPublishing:
  defaultPubsubName: pubsub
  topicMapping:
    # Three different events, same topic, different routing keys
    "invoice.validated":
      topic: "test.connection"
      routing_key: "valid"
    
    "invoice.invalidated":
      topic: "test.connection"
      routing_key: "invalid"
    
    "invoice.analysis.error":
      topic: "test.connection"
      routing_key: "error"
```

### Event Flow

```
1. Handler processes event
   ↓
2. Returns HandlerResult with event_type
   ↓
3. ProcessingService detects event_type
   ↓
4. Creates new CloudEvent
   ↓
5. Publishes to RabbitMQ with routing key
   ↓
6. Downstream systems receive event
```

### When to Use HandlerResult

**Use HandlerResult when:**
- ✅ You want to publish events automatically
- ✅ You need type-safe results
- ✅ You want to stop the handler chain
- ✅ You need structured metadata

**Use None when:**
- ✅ You want to continue to the next handler
- ✅ You're enriching context for other handlers
- ✅ You're doing validation only

**Use plain dict when:**
- ✅ You need backward compatibility
- ✅ You don't need event publishing
- ✅ You want to stop chain without publishing

### Multiple Event Types Example

```python
async def handle_event(self, event, context) -> Optional[HandlerResult]:
    result = await self.process(event.data)
    
    # Different events based on result
    if result["score"] > 0.9:
        return HandlerResult(
            data=result,
            event_type="high.confidence.result"
        )
    elif result["score"] > 0.5:
        return HandlerResult(
            data=result,
            event_type="medium.confidence.result"
        )
    else:
        return HandlerResult(
            data=result,
            event_type="low.confidence.result"
        )
```

### Error Handling with Events

Always publish error events for monitoring:

```python
try:
    result = await self.risky_operation()
    return HandlerResult(
        data=result,
        event_type="operation.success"
    )
except ValidationError as e:
    return HandlerResult(
        data={"error": str(e)},
        event_type="operation.validation.error",
        metadata={"error_type": "validation"}
    )
except TimeoutError as e:
    return HandlerResult(
        data={"error": "Timeout"},
        event_type="operation.timeout.error",
        metadata={"error_type": "timeout"}
    )
```

## Common Patterns

### Pattern 1: Validation → Processing

```python
# Handler 1: Validate (priority=10)
async def handle_event(self, event, context):
    if not valid:
        return {"error": "Invalid"}
    context["validated"] = True
    return None  # Continue

# Handler 2: Process (priority=20)
async def handle_event(self, event, context):
    if context.get("validated"):
        return {"result": "processed"}
```

### Pattern 2: Conditional Processing

```python
async def can_handle_event(self, event, context):
    # Only handle urgent invoices
    return event.data.get("priority") == "urgent"
```

### Pattern 3: Multiple Handlers Enrich, One Processes

```python
# Handler 1: Add customer data (priority=10)
context["customer"] = customer_data
return None

# Handler 2: Add product data (priority=20)
context["products"] = product_data
return None

# Handler 3: Process with all data (priority=30)
return process(context["customer"], context["products"])
```

## Testing Handlers

Test handlers independently:

```python
import pytest
from base.src.models import CloudEvent

@pytest.mark.asyncio
async def test_my_handler():
    handler = MyHandler()
    
    event = CloudEvent(
        specversion="1.0",
        id="test-123",
        source="test",
        type="invoice.received",
        data={"invoice_id": "INV-001"}
    )
    
    context = {}
    
    # Test can_handle
    assert await handler.can_handle_event(event, context) is True
    
    # Test handle
    result = await handler.handle_event(event, context)
    assert result["status"] == "processed"
```

## Tips for Junior Developers

1. **Start Simple** - Create a handler that just logs the event
2. **One Job** - Each handler should do one thing
3. **Use Context** - Share data between handlers via context
4. **Return None** - To let other handlers run
5. **Return Result** - To stop the chain
6. **Test First** - Write tests before complex logic
7. **Check Examples** - Look at `custom/src/handlers/` for real examples

## Next Steps

- Learn about [AI Agents](./llm-agents.md)
- Understand [Event Routing](./event-routing.md)
- Read about [Testing](./testing.md)
