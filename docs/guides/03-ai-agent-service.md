# Guide: Build an AI Agent Service

**Goal:** Combine events, handlers, and LLM agents for intelligent processing.

**Time:** 45 minutes | **Difficulty:** Advanced

**Prerequisites:** Complete [Event-Driven Service](02-event-driven-service.md) guide first.

---

## What You'll Build

An invoice analyzer that:
1. Receives `invoice.submitted` events
2. Uses an AI agent to analyze invoice content
3. Extracts structured data (amount, vendor, date)
4. Publishes `invoice.analyzed` events with results

---

## Step 1: Set Up Your API Key

Get an OpenAI API key from [platform.openai.com](https://platform.openai.com).

**File:** `.env` (or `secrets.toml`)

```
OPENAI_API_KEY=sk-...
```

---

## Step 2: Define Output Models

**File:** `src/models.py`

```python
from pydantic import BaseModel

class InvoiceData(BaseModel):
    """Structured invoice data."""
    vendor: str
    amount: float
    date: str
    description: str

class InvoiceAnalyzedEvent(BaseModel):
    """Event when invoice is analyzed."""
    invoice_id: str
    data: InvoiceData
    status: str
```

---

## Step 3: Create System Prompt

**File:** `prompts/invoice_analyzer.prompt`

```
You are an invoice analyzer. Extract the following information from invoices:
- Vendor name
- Invoice amount (as a number)
- Invoice date (as YYYY-MM-DD)
- Brief description

Return the data as JSON with keys: vendor, amount, date, description.
Be precise and extract only factual information from the invoice.
```

---

## Step 4: Build Your Agent

**File:** `src/agents.py`

```python
from pathlib import Path
from pydantic_ai import Agent, Tool
from blueprint.agents import AgentBuilder, Config
from .models import InvoiceData

def create_invoice_agent(config: Config) -> Agent:
    """Create the invoice analyzer agent."""

    agent = (
        AgentBuilder(config, runtime_name="invoice_analyzer")
        .with_model_from_config("invoice_analyzer")
        .with_system_prompt_file("invoice_analyzer")
        .with_result_type(InvoiceData)
        .build()
    )

    return agent
```

---

## Step 5: Create Event Handler with Agent

**File:** `src/handlers.py`

```python
from blueprint.agents import EventHandler, HandlerResult
from cloudevents.http import CloudEvent
from .models import InvoiceAnalyzedEvent

class InvoiceHandler(EventHandler):
    """Handle invoice.submitted events."""

    async def can_handle_event(self, event: CloudEvent, context) -> bool:
        """Check if this is an invoice event."""
        return event.get_type() == "invoice.submitted"

    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        """Analyze invoice with AI agent."""
        data = event.get_data()
        invoice_id = data.get("invoice_id")
        invoice_text = data.get("content")

        # Get agent from registry
        agent = self._component_registry.get_agent("invoice_analyzer")

        # Run agent to analyze invoice
        result = await agent.run(invoice_text)

        # Extract structured data
        analysis = result.data

        # Publish analyzed event
        return HandlerResult(
            event_type="invoice.analyzed",
            data=InvoiceAnalyzedEvent(
                invoice_id=invoice_id,
                data=analysis,
                status="analyzed"
            ).model_dump()
        )
```

---

## Step 6: Update Main Application

**File:** `src/main.py`

```python
from pathlib import Path
from blueprint.agents import AppBuilder, Config
from .agents import create_invoice_agent
from .handlers import InvoiceHandler
from .api import InvoiceRestApi

config = Config(
    settings_files=["settings.toml", "secrets.toml"],
    root_path=Path(__file__).parent.parent,
)

# Create agent
invoice_agent = create_invoice_agent(config)

# Build app
app = (
    AppBuilder(config)
    .with_agent(invoice_agent)
    .with_handler(InvoiceHandler)
    .with_rest_api(InvoiceRestApi())
    .build()
)
```

---

## Step 7: Configure Settings

**File:** `settings.toml`

```toml
[default]
app_name = "invoice-analyzer"
log_level = "INFO"

[default.ai.invoice_analyzer]
provider = "openai"
model_name = "gpt-4-mini"

[default.prompt.invoice_analyzer]
system_prompt_name = "invoice_analyzer"

[default.event_publishing]
enabled = true
dapr_http_port = 3500

[[default.event_publishing.topic_mapping]]
topic = "invoice.submitted"
subscription_path = "/dapr/subscribe/invoice.submitted"

[[default.event_publishing.topic_mapping]]
topic = "invoice.analyzed"
```

**File:** `secrets.toml`

```toml
[default.ai.invoice_analyzer]
api_key = "${OPENAI_API_KEY}"
```

---

## Step 8: Run Your Service

```bash
dapr run --app-id invoice-analyzer \
  --app-port 8000 \
  --dapr-http-port 3500 \
  --resources-path ./dapr/components \
  uvicorn src.main:app --reload
```

---

## Step 9: Test with an Invoice

Publish an invoice event:
```bash
curl -X POST http://localhost:3500/v1.0/publish/pubsub/invoice.submitted \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_id": "INV-001",
    "content": "Invoice from Acme Corp for $1,500 dated 2025-11-26. Services rendered."
  }'
```

Check logs to see:
1. Handler receives event
2. Agent analyzes invoice
3. `invoice.analyzed` event is published with extracted data

---

## Step 10: Add Tools to Your Agent

Let your agent call external functions:

**File:** `src/agents.py`

```python
from pydantic_ai import Tool

async def validate_vendor(vendor: str) -> bool:
    """Check if vendor exists in database."""
    # Your database logic
    return True

def create_invoice_agent(config: Config) -> Agent:
    agent = (
        AgentBuilder(config, runtime_name="invoice_analyzer")
        .with_model_from_config("invoice_analyzer")
        .with_system_prompt_file("invoice_analyzer")
        .with_tools([
            Tool(
                name="validate_vendor",
                function=validate_vendor,
                description="Check if vendor exists"
            )
        ])
        .with_result_type(InvoiceData)
        .build()
    )
    return agent
```

---

## Key Concepts

- **AgentBuilder** — Configure AI agents with models, prompts, and tools
- **Pydantic AI** — Framework for building AI applications with type safety
- **System Prompt** — Instructions that guide the AI's behavior
- **Result Type** — Pydantic model for structured AI outputs
- **Tools** — Functions the AI can call to get information
- **Chain Integration** — Agents work seamlessly with handlers and events

---

## Debugging

Enable debug logging:
```toml
log_level = "DEBUG"
```

Use VS Code debugger to step through agent execution:
1. Set breakpoint in handler
2. Launch with F5
3. Inspect agent result before publishing

---

## Performance Tips

- Use `gpt-4-mini` for faster, cheaper responses
- Cache prompts in `settings.toml` to avoid reloading
- Use tools to avoid hallucinations
- Set `max_tokens` to limit response length

---

## What's Next?

- Add caching? → Check [Configuration](../README.md#-configuration)
- Deploy? → [Deployment Guide](../deployment.md) (coming soon)
- Need help? → [Troubleshooting](../troubleshooting.md)
