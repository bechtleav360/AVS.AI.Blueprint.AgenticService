# Getting Started

**Time to complete:** 30 minutes  
**Difficulty:** Beginner

This guide helps you understand and start using the Agent Blueprint framework.

## What is This Framework?

A framework for building **event-driven microservices** that use **AI agents** to process data.

**Simple explanation:**
1. Events come in (like "new invoice received")
2. Handlers process them step-by-step
3. AI agents help with complex tasks
4. Results go out as events

## Architecture Overview

```
┌─────────────┐
│   Events    │  (RabbitMQ/Dapr)
└──────┬──────┘
       ↓
┌─────────────────────────────────┐
│      Event Handlers             │
│  ┌──────────┐  ┌──────────┐   │
│  │ Validate │→ │ Enrich   │→  │
│  └──────────┘  └──────────┘   │
│       ↓                         │
│  ┌──────────┐                  │
│  │ Process  │ ← AI Agent       │
│  └──────────┘                  │
└──────────┬──────────────────────┘
           ↓
    ┌──────────┐
    │  Result  │
    └──────────┘
```

## Key Concepts

### 1. Events
Messages that trigger processing:
```python
{
    "type": "invoice.received",
    "data": {"invoice_text": "..."}
}
```

### 2. Handlers
Process events step-by-step:
- **ValidationHandler** - Check if data is valid
- **EnrichmentHandler** - Add more data
- **ProcessingHandler** - Do the main work

### 3. AI Agents
Smart assistants that:
- Understand natural language
- Use tools you provide
- Return structured results

### 4. Chain of Responsibility
Handlers run in order, each can:
- Process and stop (return result)
- Process and continue (return None)

## Quick Start

### 1. Project Structure

```
custom/
├── src/
│   ├── main.py              # App entry point
│   ├── handlers/            # Your event handlers
│   ├── models/              # Data models
│   ├── services/            # Business logic
│   └── prompts/             # AI prompts
├── settings.toml            # Configuration
└── tests/                   # Your tests
```

### 2. Create a Handler

File: `custom/src/handlers/my_handler.py`

```python
from base.src.handler import EventHandler
from base.src.models import CloudEvent

class MyHandler(EventHandler):
    def __init__(self):
        super().__init__("MyHandler", priority=20)
    
    async def can_handle_event(self, event, context):
        """Should I process this event?"""
        return event.type == "invoice.received"
    
    async def handle_event(self, event, context):
        """Process the event."""
        invoice_text = event.data.get("invoice_text")
        
        # Simple processing
        return {
            "status": "processed",
            "invoice_length": len(invoice_text)
        }
```

### 3. Register Handler

File: `custom/src/main.py`

```python
from .handlers import MyHandler

app = (
    AppBuilder(settings_files=settings_files, root_path=project_root)
    .with_handler(MyHandler)    # Add your handler
    .build()
)
```

### 4. Run the Service

```bash
# Start the service
uvicorn custom.src.main:app --reload

# Test it
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"invoice_text": "Invoice #123..."}'
```

## Adding an AI Agent

### 1. Create a Tool

File: `custom/src/services/my_services.py`

```python
class MyService:
    @staticmethod
    async def analyze_tool(ctx, data):
        """Analyze the data."""
        # Your logic here
        return {"analysis": "complete"}
```

### 2. Build the Agent

File: `custom/src/main.py`

```python
from pydantic_ai import Tool
from .services import MyService

# Build agent
my_agent = (
    AgentBuilder(config, "my_analyzer")
    .with_model("gpt-4")
    .with_system_prompt_text("You are a helpful analyzer")
    .with_tools([
        Tool("analyze", MyService.analyze_tool)
    ])
    .build()
)

# Register agent
app = (
    AppBuilder(...)
    .with_agent(my_agent)
    .build()
)
```

### 3. Use in Handler

```python
class MyHandler(EventHandler):
    async def handle_event(self, event, context):
        # Get agent
        agent = self._get_agent("my_analyzer")
        
        # Run it
        result = await agent.run("Analyze this data: ...")
        
        return {"result": result.data}
```

## Configuration

### settings.toml

```toml
[app]
name = "my-service"
port = 8000

[runtime.my_analyzer]
model_name = "gpt-4"
temperature = 0.1

[prompt]
custom_path = "custom/src/prompts"
```

### Environment Variables

```bash
# Override settings
RUNTIME__MY_ANALYZER__MODEL_NAME=gpt-3.5-turbo
APP__PORT=8080
```

## Common Workflows

### Workflow 1: Simple Processing

```python
# Handler processes and returns
class SimpleHandler(EventHandler):
    async def handle_event(self, event, context):
        result = process(event.data)
        return {"result": result}
```

### Workflow 2: Multi-Step Processing

```python
# Handler 1: Validate
class ValidationHandler(EventHandler):
    async def handle_event(self, event, context):
        if not valid(event.data):
            return {"error": "Invalid"}
        context["validated"] = True
        return None  # Continue

# Handler 2: Process
class ProcessingHandler(EventHandler):
    async def handle_event(self, event, context):
        if context.get("validated"):
            return {"result": "processed"}
```

### Workflow 3: AI-Powered Processing

```python
class AIHandler(EventHandler):
    async def handle_event(self, event, context):
        # Get AI agent
        agent = self._get_agent("analyzer")
        
        # Prepare instruction
        instruction = f"Analyze: {event.data['text']}"
        
        # Run agent
        result = await agent.run(instruction)
        
        return {"analysis": result.data}
```

## Testing

### Test a Handler

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
        data={"invoice_text": "Test"}
    )
    
    result = await handler.handle_event(event, {})
    
    assert result["status"] == "processed"
```

### Run Tests

```bash
pytest custom/tests/ -v
```

## Development Tips

### For Junior Developers

1. **Start Small** - Create one simple handler first
2. **Test Often** - Write tests as you go
3. **Use Examples** - Look at `custom/src/handlers/` for patterns
4. **Read Logs** - Check console output to understand flow
5. **Ask Questions** - Use comments to explain your code

### Common Mistakes

❌ **Don't** create handlers that do everything
✅ **Do** create small, focused handlers

❌ **Don't** hardcode prompts in code
✅ **Do** use prompt files

❌ **Don't** forget to register handlers
✅ **Do** add them in `main.py`

❌ **Don't** ignore errors
✅ **Do** use try/except blocks

## Project Checklist

- [ ] Handler created
- [ ] Handler registered in main.py
- [ ] Tests written
- [ ] Prompts in files (if using AI)
- [ ] Configuration updated
- [ ] Error handling added
- [ ] Logging added

## Next Steps

1. **Learn Handlers** - Read [Creating Event Handlers](./handlers.md)
2. **Learn AI Agents** - Read [Working with AI Agents](./llm-agents.md)
3. **Configure** - Read [Configuration Guide](./configuration/README.md)
4. **Deploy** - Read [Deployment Guide](./deployment.md)

## Getting Help

- Check [Troubleshooting](./troubleshooting.md)
- Look at examples in `custom/src/handlers/`
- Read inline code comments
- Check test files for usage examples
