# Concept: Response Handling

Learn how to parse and validate AI agent responses.

---

## What is Response Handling?

When an AI agent finishes thinking, it returns a response. Response handling is the process of:
1. **Parsing** — Convert the response to structured data
2. **Validating** — Ensure the data is correct
3. **Using** — Work with the validated data

---

## Define Response Types

### Simple Response

```python
from pydantic import BaseModel

class InvoiceAnalysis(BaseModel):
    """Structured invoice analysis result."""
    vendor: str
    amount: float
    date: str
    description: str
```

### Response with Validation

```python
from pydantic import BaseModel, Field

class InvoiceAnalysis(BaseModel):
    """Structured invoice analysis result."""
    vendor: str = Field(..., description="Vendor name")
    amount: float = Field(..., gt=0, description="Invoice amount (must be positive)")
    date: str = Field(..., description="Invoice date (YYYY-MM-DD format)")
    description: str = Field(..., min_length=1, description="Invoice description")
```

### Complex Response

```python
from pydantic import BaseModel
from typing import Optional

class LineItem(BaseModel):
    description: str
    quantity: int
    unit_price: float
    total: float

class InvoiceAnalysis(BaseModel):
    vendor: str
    amount: float
    date: str
    line_items: list[LineItem]
    notes: Optional[str] = None
```

---

## Register Response Type with Agent

```python
from blueprint.agents import AgentBuilder

agent = (
    AgentBuilder(config)
    .with_model_from_config("invoice_analyzer")
    .with_system_prompt_file("invoice_analyzer")
    .with_result_type(InvoiceAnalysis)  # Register response type
    .build()
)
```

---

## Use Agent Response

### Basic Usage

```python
class InvoiceHandler(EventHandler):
    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        data = event.get_data()

        agent = self._component_registry.get_agent("invoice_analyzer")

        # Run agent - returns structured response
        result = await agent.run(data["invoice_text"])

        # Access response data
        analysis = result.data  # This is InvoiceAnalysis instance

        print(f"Vendor: {analysis.vendor}")
        print(f"Amount: {analysis.amount}")
        print(f"Date: {analysis.date}")

        return HandlerResult(
            event_type="invoice.analyzed",
            data=analysis.model_dump()  # Convert to dict for event
        )
```

### Validation During Use

```python
class InvoiceService(BusinessService):
    def get_name(self) -> str:
        return "invoice_service"

    async def analyze(self, invoice_text: str) -> dict:
        agent = self._component_registry.get_agent("invoice_analyzer")

        try:
            result = await agent.run(invoice_text)
            analysis = result.data

            # Validate response
            if analysis.amount <= 0:
                raise ValueError("Amount must be positive")

            if not analysis.vendor:
                raise ValueError("Vendor is required")

            return analysis.model_dump()

        except ValueError as e:
            logger.error(f"Invalid response: {e}")
            raise
```

---

## Response Validation

### Pydantic Validation

Pydantic automatically validates responses:

```python
class InvoiceAnalysis(BaseModel):
    vendor: str  # Required
    amount: float  # Must be a number
    date: str  # Required
    description: str  # Required

# If agent returns:
# {"vendor": "Acme", "amount": "invalid", "date": "2025-11-26"}
# Pydantic raises ValidationError because amount is not a number
```

### Custom Validation

```python
from pydantic import BaseModel, field_validator

class InvoiceAnalysis(BaseModel):
    vendor: str
    amount: float
    date: str

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        if v > 1000000:
            raise ValueError("Amount exceeds maximum limit")
        return v

    @field_validator("date")
    @classmethod
    def validate_date(cls, v):
        # Ensure date is in YYYY-MM-DD format
        try:
            from datetime import datetime
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format")
        return v
```

---

## Error Handling

### Catch Validation Errors

```python
from pydantic import ValidationError


async def analyze_invoice(invoice_text: str) -> dict:
    agent = self._registry.get_agent("invoice_analyzer")

    try:
        result = await agent.run(invoice_text)
        analysis = result.data
        return analysis.model_dump()

    except ValidationError as e:
        logger.error(f"Response validation failed: {e}")
        # Return error response
        return {
            "error": "Invalid response from agent",
            "details": str(e)
        }
```

### Handle Missing Fields

```python
from typing import Optional

class InvoiceAnalysis(BaseModel):
    vendor: str
    amount: float
    date: str
    notes: Optional[str] = None  # Optional field

# Agent can return response without "notes" field
# Pydantic will set it to None
```

---

## Real-World Example

### Complete Invoice Processing

```python
from pydantic import BaseModel, field_validator
from blueprint.agents import AgentBuilder, EventHandler, HandlerResult
from cloudevents.http import CloudEvent

class InvoiceAnalysis(BaseModel):
    """Validated invoice analysis."""
    vendor: str
    amount: float
    date: str
    description: str

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError("Amount must be positive")
        return v

class InvoiceHandler(EventHandler):
    async def can_handle_event(self, event: CloudEvent, context) -> bool:
        return event.get_type() == "invoice.submitted"

    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        data = event.get_data()

        agent = self._component_registry.get_agent("invoice_analyzer")

        try:
            # Run agent with response type validation
            result = await agent.run(data["invoice_text"])
            analysis = result.data  # Automatically validated

            logger.info(f"Analyzed invoice from {analysis.vendor}: ${analysis.amount}")

            # Store in database
            service = self._component_registry.get_service("invoice_service")
            await service.save_analysis(analysis)

            return HandlerResult(
                event_type="invoice.analyzed",
                data=analysis.model_dump()
            )

        except ValidationError as e:
            logger.error(f"Invalid response: {e}")
            # Publish error event
            return HandlerResult(
                event_type="invoice.analysis_failed",
                data={"error": str(e)}
            )

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            raise  # Let exception propagate
```

---

## Response Transformation

### Convert to Different Format

```python
class InvoiceAnalysis(BaseModel):
    vendor: str
    amount: float
    date: str

# Convert to dict
analysis_dict = analysis.model_dump()
# {"vendor": "Acme", "amount": 1500.0, "date": "2025-11-26"}

# Convert to JSON string
analysis_json = analysis.model_dump_json()
# '{"vendor": "Acme", "amount": 1500.0, "date": "2025-11-26"}'

# Convert to custom format
def to_database_record(analysis: InvoiceAnalysis) -> dict:
    return {
        "vendor_name": analysis.vendor,
        "invoice_amount": analysis.amount,
        "invoice_date": analysis.date
    }
```

### Partial Responses

```python
class InvoiceAnalysis(BaseModel):
    vendor: str
    amount: float
    date: str
    description: Optional[str] = None

# Agent can return partial response
# Pydantic fills in missing optional fields with None
analysis = InvoiceAnalysis(
    vendor="Acme",
    amount=1500.0,
    date="2025-11-26"
    # description is None
)
```

---

## Best Practices

1. **Define clear response types** — Use Pydantic models
2. **Add validation** — Use field validators for business rules
3. **Make fields optional** — If agent might not provide them
4. **Document fields** — Use Field descriptions
5. **Handle errors gracefully** — Catch ValidationError
6. **Log responses** — Debug what agent returns
7. **Test response types** — Verify agent returns valid data

---

## Common Patterns

### Retry on Invalid Response

```python
async def analyze_with_retry(invoice_text: str, max_retries: int = 3) -> InvoiceAnalysis:
    agent = self._registry.get_agent("invoice_analyzer")

    for attempt in range(max_retries):
        try:
            result = await agent.run(invoice_text)
            return result.data
        except ValidationError as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            # Retry with improved prompt
```

### Fallback Response

```python
async def analyze_invoice(invoice_text: str) -> InvoiceAnalysis:
    agent = self._registry.get_agent("invoice_analyzer")

    try:
        result = await agent.run(invoice_text)
        return result.data
    except ValidationError:
        # Return default response if agent fails
        return InvoiceAnalysis(
            vendor="Unknown",
            amount=0.0,
            date="",
            description="Failed to analyze"
        )
```

### Response Enrichment

```python
async def analyze_and_enrich(invoice_text: str) -> dict:
    agent = self._registry.get_agent("invoice_analyzer")
    result = await agent.run(invoice_text)
    analysis = result.data

    # Enrich with additional data
    service = self._registry.get_service("vendor_service")
    vendor_info = await service.get_vendor(analysis.vendor)

    return {
        **analysis.model_dump(),
        "vendor_info": vendor_info
    }
```

---

## Next Steps

- [Tools](tools.md) — Give agents functions to call
- [Exception Handling](exception-handling.md) — Handle errors gracefully
- [Caching](caching.md) — Cache responses for performance
