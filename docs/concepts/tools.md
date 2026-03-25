# Concept: Tools

Learn how to give AI agents functions they can call.

---

## What are Tools?

Tools are functions that your AI agent can call to get information or perform actions. Instead of the agent making up answers, it can call a tool to look up real data.

**Example:** Instead of the agent guessing a user's account balance, give it a tool to look it up in the database.

---

## Why Use Tools?

- **Accuracy** — Agent gets real data instead of guessing
- **Safety** — Agent can only call functions you allow
- **Flexibility** — Agent decides when to use tools
- **Transparency** — You see what functions the agent called

---

## Define a Tool

### Simple Tool

```python
from pydantic_ai import Tool

async def get_user(user_id: str) -> dict:
    """Look up a user by ID."""
    # Your database logic
    return {
        "id": user_id,
        "name": "John Doe",
        "email": "john@example.com"
    }

# Create tool
user_tool = Tool(
    name="get_user",
    function=get_user,
    description="Look up a user by ID"
)
```

### Tool with Parameters

```python
async def calculate_total(items: list[dict]) -> float:
    """Calculate total price of items."""
    return sum(item["price"] * item["quantity"] for item in items)

tool = Tool(
    name="calculate_total",
    function=calculate_total,
    description="Calculate total price of items with quantities"
)
```

### Tool with Validation

```python
from pydantic import BaseModel

class UserQuery(BaseModel):
    user_id: str
    include_orders: bool = False

async def get_user_info(query: UserQuery) -> dict:
    """Get user information."""
    user = await database.get_user(query.user_id)

    if query.include_orders:
        user["orders"] = await database.get_user_orders(query.user_id)

    return user

tool = Tool(
    name="get_user_info",
    function=get_user_info,
    description="Get user information with optional order history"
)
```

---

## Register Tools with Agent

### Single Tool

```python
from blueprint.agents import AgentBuilder

agent = (
    AgentBuilder(config)
    .with_model_from_config("my_agent")
    .with_system_prompt_file("system")
    .with_tools([user_tool])
    .with_result_type(MyOutput)
    .build()
)
```

### Multiple Tools

```python
agent = (
    AgentBuilder(config)
    .with_model_from_config("my_agent")
    .with_system_prompt_file("system")
    .with_tools([
        user_tool,
        order_tool,
        inventory_tool,
        payment_tool
    ])
    .with_result_type(MyOutput)
    .build()
)
```

---

## Real-World Example

### Invoice Analyzer with Tools

```python
from pydantic import BaseModel
from pydantic_ai import Tool

class VendorInfo(BaseModel):
    vendor_id: str
    name: str
    is_approved: bool
    discount_rate: float

async def lookup_vendor(vendor_name: str) -> VendorInfo:
    """Look up vendor information by name."""
    vendor = await database.get_vendor(vendor_name)
    return VendorInfo(**vendor)

async def validate_amount(amount: float) -> dict:
    """Validate invoice amount against limits."""
    return {
        "valid": amount > 0 and amount < 100000,
        "reason": "Amount is within acceptable range"
    }

async def check_duplicate(invoice_id: str) -> bool:
    """Check if invoice was already processed."""
    return await database.invoice_exists(invoice_id)

# Create tools
vendor_tool = Tool(
    name="lookup_vendor",
    function=lookup_vendor,
    description="Look up vendor information by name"
)

amount_tool = Tool(
    name="validate_amount",
    function=validate_amount,
    description="Validate invoice amount is within limits"
)

duplicate_tool = Tool(
    name="check_duplicate",
    function=check_duplicate,
    description="Check if invoice was already processed"
)

# Build agent with tools
agent = (
    AgentBuilder(config)
    .with_model_from_config("invoice_analyzer")
    .with_system_prompt_file("invoice_analyzer")
    .with_tools([vendor_tool, amount_tool, duplicate_tool])
    .with_result_type(InvoiceAnalysis)
    .build()
)
```

### System Prompt Using Tools

**File:** `prompts/invoice_analyzer.prompt`

```
You are an invoice analyzer. Your job is to analyze invoices and extract key information.

When analyzing an invoice:
1. Extract vendor name, amount, and date
2. Use lookup_vendor to verify the vendor is approved
3. Use validate_amount to check the amount is reasonable
4. Use check_duplicate to ensure this invoice wasn't already processed
5. Return the analysis with all extracted data

Be thorough and use all available tools to validate the invoice.
```

---

## Tool Execution Flow

```
User Input
    ↓
Agent reads input
    ↓
Agent decides to use tools
    ↓
Agent calls lookup_vendor("Acme Corp")
    ↓
Tool executes and returns vendor info
    ↓
Agent calls validate_amount(1500)
    ↓
Tool executes and returns validation result
    ↓
Agent calls check_duplicate("INV-001")
    ↓
Tool executes and returns duplicate check
    ↓
Agent generates final response
    ↓
Response returned to user
```

---

## Error Handling in Tools

### Graceful Failures

```python
async def lookup_vendor(vendor_name: str) -> dict:
    """Look up vendor information."""
    try:
        vendor = await database.get_vendor(vendor_name)
        if not vendor:
            return {
                "found": False,
                "error": f"Vendor '{vendor_name}' not found"
            }
        return {
            "found": True,
            "vendor": vendor
        }
    except Exception as e:
        return {
            "found": False,
            "error": f"Database error: {str(e)}"
        }

tool = Tool(
    name="lookup_vendor",
    function=lookup_vendor,
    description="Look up vendor information"
)
```

### Validation in Tools

```python
async def process_payment(amount: float, vendor_id: str) -> dict:
    """Process payment to vendor."""
    # Validate inputs
    if amount <= 0:
        raise ValueError("Amount must be positive")

    if not vendor_id:
        raise ValueError("Vendor ID is required")

    # Process payment
    result = await payment_service.process(amount, vendor_id)

    return {
        "success": True,
        "transaction_id": result.id,
        "amount": amount
    }

tool = Tool(
    name="process_payment",
    function=process_payment,
    description="Process payment to vendor"
)
```

---

## Tool Limitations

### What Tools Can Do

✅ Query databases
✅ Call APIs
✅ Perform calculations
✅ Validate data
✅ Look up information

### What Tools Should NOT Do

❌ Make decisions (agent does that)
❌ Return sensitive data (filter in tool)
❌ Have side effects without confirmation
❌ Take too long (timeout after 30 seconds)

---

## Best Practices

1. **Clear descriptions** — Agent uses descriptions to decide when to call tools
2. **Simple inputs** — Keep tool parameters simple and well-defined
3. **Fast execution** — Tools should return quickly (< 5 seconds)
4. **Error handling** — Return errors gracefully, don't raise exceptions
5. **Limit tools** — 5-10 tools per agent is ideal
6. **Document behavior** — Explain what each tool does

---

## Debugging Tools

### Log Tool Calls

```python
async def lookup_vendor(vendor_name: str) -> dict:
    logger.info(f"Tool called: lookup_vendor({vendor_name})")

    result = await database.get_vendor(vendor_name)

    logger.debug(f"Tool result: {result}")

    return result
```

### Test Tools Independently

```python
import asyncio

async def test_lookup_vendor():
    result = await lookup_vendor("Acme Corp")
    print(f"Result: {result}")

asyncio.run(test_lookup_vendor())
```

### Monitor Tool Usage

Enable debug logging to see which tools the agent calls:

```toml
[default]
log_level = "DEBUG"
```

---

## Common Patterns

### Caching Tool Results

```python
async def lookup_vendor(vendor_name: str) -> dict:
    cache = self._registry.cache_service

    # Check cache
    cached = cache.get("vendors", vendor_name)
    if cached:
        return cached

    # Query database
    result = await database.get_vendor(vendor_name)

    # Cache for 1 hour
    cache.set("vendors", vendor_name, result, ttl=3600)

    return result
```

### Chaining Tools

```python
async def process_invoice(invoice_id: str) -> dict:
    # First tool: get invoice
    invoice = await lookup_invoice(invoice_id)

    # Second tool: validate vendor
    vendor = await lookup_vendor(invoice["vendor"])

    # Third tool: check amount
    validation = await validate_amount(invoice["amount"])

    return {
        "invoice": invoice,
        "vendor": vendor,
        "validation": validation
    }
```

---

## Next Steps

- [Response Handling](response-handling.md) — Parse and validate AI responses
- [Exception Handling](exception-handling.md) — Handle errors gracefully
- [Caching](caching.md) — Cache tool results for performance
