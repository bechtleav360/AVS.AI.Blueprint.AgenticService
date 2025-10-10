# Building LLM Agents with Pydantic AI

**Time to complete:** 30 minutes
**Difficulty:** Intermediate

This guide teaches you how to build AI-powered agents using Pydantic AI.

## What Is an LLM Agent?

An **LLM Agent** is an AI assistant that can:
- Understand natural language
- Use tools to perform tasks
- Make decisions based on context
- Return structured data

**Example:** An invoice processing agent that:
1. Reads unstructured invoice text
2. Extracts key information
3. Calls a calculation tool
4. Returns validated results

## When to Use LLM Agents

Use LLM agents when you need:

✅ **Natural language understanding**
- Parse unstructured text
- Extract entities and relationships
- Understand user intent

✅ **Complex decision making**
- Analyze data and make recommendations
- Handle ambiguous inputs
- Adapt to different scenarios

✅ **Tool orchestration**
- Call multiple APIs in sequence
- Combine data from different sources
- Perform multi-step workflows

❌ **Don't use for:**
- Simple rule-based logic (use handlers instead)
- High-frequency operations (too slow/expensive)
- Deterministic calculations (use regular functions)

## Architecture Overview

```
┌─────────────┐
│   Handler   │ ─── Sets context["use_agent"] = True
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│ ProcessingService│ ─── Invokes agent runtime
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  Agent Runtime  │ ─── Your custom agent class
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│  Pydantic AI    │ ─── Calls LLM with tools
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│   LLM           │ ─── Generates response
└─────────────────┘
```

## Prerequisites

- Completed [Getting Started Guide](getting-started.md)
- Understanding of [Handlers](handlers.md)
- API key for OpenAI or access to vLLM

## Step 1: Create Agent Runtime Class

The agent runtime wraps Pydantic AI and provides the framework integration.

### Basic Structure

Create `custom/src/agent/runtime.py`:

```python
"""AI agent runtime for invoice processing."""

import logging
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel

from base.src.agent import BaseAgent
from base.src.config import Config

from ..models.domain import InvoiceAnalysisOutput, ProcessingContext

logger = logging.getLogger(__name__)


class InvoiceAgentRuntime(BaseAgent):
    """Agent runtime for processing invoices with AI."""

    def __init__(self, config: Config):
        """Initialize the agent runtime."""
        super().__init__(config)
        self.agent = None

    def _get_prompt_name(self) -> str:
        """Return the prompt file name."""
        return "invoice_processor.txt"

    def _get_tools(self) -> list:
        """Return tools for the agent."""
        from .tools import Tools
        tools_instance = Tools()
        return [tools_instance.calculate_invoice]

    def _get_processing_context_type(self) -> type:
        """Return the context model type."""
        return ProcessingContext

    def _get_result_type(self) -> type:
        """Return the output model type."""
        return InvoiceAnalysisOutput
```

### What Each Method Does

| Method | Purpose | Example |
|--------|---------|---------|
| `_get_prompt_name()` | Name of prompt file | `"invoice_processor.txt"` |
| `_get_tools()` | Tools the AI can use | `[calculate_invoice, lookup_customer]` |
| `_get_processing_context_type()` | Input data model | `ProcessingContext` |
| `_get_result_type()` | Output data model | `InvoiceAnalysisOutput` |

## Step 2: Create Data Models

Define input and output models in `custom/src/models/domain.py`:

```python
"""Domain models for invoice processing."""

from typing import Optional
from pydantic import BaseModel, Field


class ProcessingContext(BaseModel):
    """Context data passed to the agent."""

    invoice_text: str = Field(..., description="Raw invoice text from OCR")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class InvoiceAnalysisOutput(BaseModel):
    """Structured output from the agent."""

    invoice_id: str = Field(..., description="Unique invoice identifier")
    status: str = Field(..., description="Processing status: valid, invalid, pending")
    summary: str = Field(..., description="Human-readable summary")
    total_amount: str = Field(..., description="Total amount as string")
    inferred_tax_amount: str = Field(..., description="Calculated tax amount")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    notes: Optional[str] = Field(None, description="Additional notes")
    metadata: dict = Field(default_factory=dict, description="Processing metadata")
```

**Why Pydantic models?**
- **Validation** - Ensures data is correct
- **Type Safety** - Catches errors early
- **Documentation** - Self-documenting code
- **Serialization** - Easy JSON conversion

## Step 3: Create System Prompt

Create `custom/prompts/invoice_processor.txt`:

```text
You are an invoice processing agent for Bechtle. You extract information from unstructured invoice text (OCR output).

When you receive invoice text:

1. Parse the text to extract:
   - invoice_id (look for "Invoice #", "Invoice No.", etc.)
   - All line items with their description, quantity, unit_price
   - Tax rates if mentioned (e.g., "19% VAT", "Tax: 19%")
   - Currency (EUR, USD, etc.)

2. Once you've extracted the data, CALL the calculate_invoice tool with an InvoiceInput containing:
   - invoice_id: the extracted ID
   - line_items: array of items with description, quantity, unit_price, and tax_rate (if found)
   - currency: the extracted currency or "EUR" as default

3. The tool will calculate totals and infer taxes, returning an InvoiceAnalysisOutput.

Do NOT calculate manually - always use the calculate_invoice tool after extracting the data from the text.

Be precise and thorough. If information is missing or unclear, note it in the output.
```

**Prompt Best Practices:**
- Be specific about what the agent should do
- Explain the tools and when to use them
- Provide examples if helpful
- Set clear expectations

## Step 4: Create Tools

Tools are functions the AI can call. Create `custom/src/agent/tools.py`:

```python
"""Tools for the invoice processing agent."""

import logging
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from ..models.domain import InvoiceAnalysisOutput

logger = logging.getLogger(__name__)


class InvoiceLineItem(BaseModel):
    """A single line item on an invoice."""

    description: str = Field(..., description="Description of the item or service")
    quantity: float = Field(..., gt=0, description="Quantity of items")
    unit_price: float = Field(..., ge=0, description="Price per unit")
    tax_rate: Optional[float] = Field(None, ge=0, le=1, description="Tax rate as decimal (e.g., 0.19 for 19%)")


class InvoiceInput(BaseModel):
    """Invoice data for calculation."""

    invoice_id: str = Field(..., description="Unique invoice identifier")
    line_items: list[InvoiceLineItem] = Field(..., min_length=1, description="List of line items")
    currency: str = Field(default="EUR", description="Currency code (ISO 4217)")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class Tools:
    """Tools available to the invoice processing agent."""

    def calculate_invoice(self, invoice: InvoiceInput) -> InvoiceAnalysisOutput:
        """Calculate invoice totals and infer taxes deterministically.

        Returns an InvoiceAnalysisOutput with computed totals and tax amounts.
        """
        logger.info("Executing calculate_invoice tool for invoice %s", invoice.invoice_id)

        total = Decimal("0")
        total_tax = Decimal("0")
        evidence = []

        for idx, item in enumerate(invoice.line_items, 1):
            # Calculate line total
            line_net = Decimal(str(item.quantity)) * Decimal(str(item.unit_price))

            # Calculate tax
            if item.tax_rate is not None:
                line_tax = line_net * Decimal(str(item.tax_rate))
            else:
                line_tax = Decimal("0")

            total += line_net + line_tax
            total_tax += line_tax

            evidence.append(
                f"Line {idx}: net={line_net:.2f}, tax_rate={item.tax_rate or 0}, tax={line_tax:.2f}"
            )

        return InvoiceAnalysisOutput(
            invoice_id=invoice.invoice_id,
            status="valid",
            summary=f"Invoice {invoice.invoice_id} processed: total {total:.2f} {invoice.currency}, inferred tax {total_tax:.2f} {invoice.currency}.",
            total_amount=f"{total:.2f}",
            inferred_tax_amount=f"{total_tax:.2f}",
            confidence=1.0,
            notes=None,
            metadata={
                "currency": invoice.currency,
                "line_item_count": len(invoice.line_items),
                "evidence": evidence,
                "recommendations": [],
                "context": {
                    "correlation_id": None,
                    "event_id": None,
                },
            },
        )
```

**Tool Design Tips:**
- Use Pydantic models for inputs
- Return structured data
- Add logging for debugging
- Handle errors gracefully
- Keep tools focused (single responsibility)

## Step 5: Register Agent Runtime

In `custom/src/main.py`:

```python
from base.src.app_builder import AppBuilder
from .agent.runtime import InvoiceAgentRuntime
from .agent.handlers import AgentInvokerHandler

app = (
    AppBuilder()
    .with_handler(AgentInvokerHandler)
    .with_agent_runtime(InvoiceAgentRuntime, is_default=True)
    .build()
)
```

## Step 6: Test Your Agent

### Via REST API

```bash
curl -X POST http://localhost:8001/api/process-resource \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_text": "Invoice #INV-2025-001\nDate: 2025-01-15\nCustomer: Bechtle AG\n\nLine Items:\n1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr\n2. Software license - Qty: 1 @ 500.00 EUR\n\nSubtotal: 2000.00 EUR\nTax (19%): 380.00 EUR\nTotal: 2380.00 EUR",
    "details": {"action": "invoke_agent"}
  }'
```

### Via Python

```python
import asyncio
from custom.src.agent.runtime import InvoiceAgentRuntime
from custom.src.models.domain import ProcessingContext
from base.src.config import Config

async def test_agent():
    config = Config()
    runtime = InvoiceAgentRuntime(config)

    context = ProcessingContext(
        invoice_text="Invoice #INV-001\nAmount: 100.00 EUR",
        metadata={"test": True}
    )

    result = await runtime.process_request(
        context=context,
        instruction="Process this invoice"
    )

    print(result)

asyncio.run(test_agent())
```

## Advanced Features

### Multiple Tools

```python
class Tools:
    """Collection of tools for the agent."""

    def calculate_invoice(self, invoice: InvoiceInput) -> InvoiceAnalysisOutput:
        """Calculate invoice totals."""
        # ... implementation ...

    def lookup_customer(self, customer_id: str) -> dict:
        """Look up customer information."""
        return {
            "customer_id": customer_id,
            "name": "Bechtle AG",
            "credit_limit": 50000.00
        }

    def validate_vat(self, vat_number: str) -> bool:
        """Validate VAT number format."""
        import re
        return bool(re.match(r"^[A-Z]{2}\d{8,12}$", vat_number))


def _get_tools(self) -> list:
    """Return all tools."""
    tools = Tools()
    return [
        tools.calculate_invoice,
        tools.lookup_customer,
        tools.validate_vat,
    ]
```

### Custom Health Check

```python
class InvoiceAgentRuntime(BaseAgent):
    # ... other methods ...

    async def custom_health_check(self) -> dict[str, Any]:
        """Check if agent is healthy."""
        try:
            # Test a simple prompt
            test_result = await self.agent.run(
                "Say 'healthy'",
                message_history=[]
            )

            return {
                "status": "healthy",
                "model": self.config.get("ai_model_name"),
                "test_response": test_result.data
            }
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return {
                "status": "unhealthy",
                "error": str(e)
            }
```

### Streaming Responses

For long-running operations:

```python
async def process_request_stream(self, context: ProcessingContext, instruction: str):
    """Process request with streaming."""
    async with self.agent.run_stream(instruction) as stream:
        async for chunk in stream:
            # Yield partial results
            yield chunk
```

### Error Handling

```python
async def process_request(self, context: ProcessingContext, instruction: str):
    """Process request with error handling."""
    try:
        result = await self.agent.run(instruction)
        return self._handle_agent_response(result)

    except ValidationError as e:
        logger.error("Validation error: %s", e)
        return InvoiceAnalysisOutput(
            invoice_id="unknown",
            status="error",
            summary=f"Validation failed: {e}",
            total_amount="0.00",
            inferred_tax_amount="0.00",
            confidence=0.0
        )

    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        raise
```

## Configuration

### OpenAI Configuration

In `custom/settings.toml`:

```toml
[default]
ai_model_provider = "openai"
ai_model_name = "gpt-4"
ai_model_timeout = 60
```

In `custom/secrets.toml`:

```toml
[default]
ai_model_api_key = "sk-your-key-here"
```

### vLLM Configuration

For self-hosted models:

```toml
[default]
ai_model_provider = "vllm"
ai_model_name = "default"
ai_model_base_url = "https://your-vllm-server.com/v1"
ai_model_timeout = 120
```

```toml
[default]
ai_model_api_key = "your-vllm-key"
```

## Best Practices

### 1. Design Clear Prompts

✅ **Good:**
```text
You are an invoice processor. Extract these fields:
- invoice_id (required)
- amount (required, must be positive)
- currency (default: EUR)

Use the calculate_invoice tool to compute totals.
```

❌ **Bad:**
```text
Process invoices and do calculations.
```

### 2. Use Structured Outputs

✅ **Good:**
```python
class InvoiceOutput(BaseModel):
    invoice_id: str
    amount: Decimal
    status: Literal["valid", "invalid"]
```

❌ **Bad:**
```python
# Returning unstructured dict
return {"result": "some text"}
```

### 3. Validate Tool Inputs

✅ **Good:**
```python
class InvoiceInput(BaseModel):
    invoice_id: str = Field(..., min_length=1)
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(..., regex=r"^[A-Z]{3}$")
```

❌ **Bad:**
```python
def calculate(invoice_id, amount, currency):
    # No validation
    pass
```

### 4. Handle Tool Errors

✅ **Good:**
```python
def calculate_invoice(self, invoice: InvoiceInput) -> InvoiceAnalysisOutput:
    try:
        result = self._calculate(invoice)
        return result
    except ZeroDivisionError:
        logger.error("Division by zero in calculation")
        return self._error_output("Invalid calculation")
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        raise
```

### 5. Log Tool Calls

```python
def calculate_invoice(self, invoice: InvoiceInput) -> InvoiceAnalysisOutput:
    logger.info("Executing calculate_invoice tool for invoice %s", invoice.invoice_id)

    result = self._calculate(invoice)

    logger.info("Calculation complete: total=%s, tax=%s",
               result.total_amount, result.inferred_tax_amount)

    return result
```

## Troubleshooting

### Agent Not Being Invoked

**Check:**
1. Is `context["use_agent"] = True` set in handler?
2. Is agent registered in `main.py`?
3. Are there errors in logs?

**Debug:**
```python
async def _handle(self, event, context):
    logger.info("Setting use_agent=True")
    context["use_agent"] = True
    context["agent_name"] = "InvoiceAgentRuntime"
    logger.info("Context: %s", context)
    return None
```

### Tool Not Being Called

**Check:**
1. Is tool registered in `_get_tools()`?
2. Does prompt mention the tool?
3. Is tool input model correct?

**Debug:** Add logging to tool:
```python
def calculate_invoice(self, invoice: InvoiceInput):
    logger.info("Tool called with: %s", invoice.dict())
    # ... rest of implementation
```

### Invalid Output Format

**Cause:** Agent returning wrong structure

**Solution:** Be explicit in prompt:
```text
IMPORTANT: You MUST call the calculate_invoice tool.
Do NOT return results directly.
The tool will return the properly formatted output.
```

### Timeout Errors

**Cause:** Request taking too long

**Solution:** Increase timeout:
```toml
[default]
ai_model_timeout = 120  # 2 minutes
```

## Performance Tips

### 1. Cache Expensive Operations

```python
from functools import lru_cache

@lru_cache(maxsize=100)
def lookup_customer(self, customer_id: str) -> dict:
    """Cached customer lookup."""
    return self._fetch_customer(customer_id)
```

### 2. Use Async for I/O

```python
async def lookup_customer(self, customer_id: str) -> dict:
    """Async customer lookup."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"/api/customers/{customer_id}")
        return response.json()
```

### 3. Limit Tool Complexity

Keep tools simple and fast:
- Avoid heavy computations
- Don't make many API calls
- Return quickly

### 4. Monitor Token Usage

```python
result = await self.agent.run(instruction)
logger.info("Tokens used: %s", result.usage())
```

## Testing Agents

### Unit Test Tools

```python
def test_calculate_invoice():
    """Test invoice calculation tool."""
    tools = Tools()

    invoice = InvoiceInput(
        invoice_id="INV-001",
        line_items=[
            InvoiceLineItem(
                description="Service",
                quantity=10,
                unit_price=100.00,
                tax_rate=0.19
            )
        ]
    )

    result = tools.calculate_invoice(invoice)

    assert result.invoice_id == "INV-001"
    assert result.status == "valid"
    assert float(result.total_amount) == 1190.00
```

### Integration Test Agent

```python
@pytest.mark.asyncio
async def test_agent_end_to_end():
    """Test full agent workflow."""
    config = Config()
    runtime = InvoiceAgentRuntime(config)

    context = ProcessingContext(
        invoice_text="Invoice #INV-001\nAmount: 100.00 EUR"
    )

    result = await runtime.process_request(
        context=context,
        instruction="Process this invoice"
    )

    assert isinstance(result, InvoiceAnalysisOutput)
    assert result.status == "valid"
```

## Next Steps

Now that you can build LLM agents:

1. **[Testing Guide](testing.md)** - Test your agents thoroughly
2. **[Deployment Guide](deployment.md)** - Deploy to production
3. **[Architecture Overview](architecture.md)** - Understand the full system

## Quick Reference

```python
# Agent runtime structure
class MyAgentRuntime(BaseAgent):
    def _get_prompt_name(self) -> str:
        return "my_prompt.txt"

    def _get_tools(self) -> list:
        return [tool1, tool2]

    def _get_processing_context_type(self) -> type:
        return MyContext

    def _get_result_type(self) -> type:
        return MyOutput

# Register agent
app = (
    AppBuilder()
    .with_agent_runtime(MyAgentRuntime, is_default=True)
    .build()
)

# Invoke from handler
context["use_agent"] = True
context["agent_input"] = data
```

---

**Next:** [Architecture Overview](architecture.md) →
