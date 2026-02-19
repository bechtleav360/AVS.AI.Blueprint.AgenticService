---
trigger: always_on
---

# Code Style and Quality Standards

## Object-Oriented Design

Follow strict OOP principles:
- Use classes and inheritance, NO global functions
- NO global variables (singleton pattern only if absolutely necessary)
- Encapsulate state within classes
- Prefer composition over inheritance where appropriate

## Type Annotations

ALWAYS use complete type hints:

✅ **Required**:
```python
async def process_item(self, item_id: str, options: dict[str, Any]) -> ItemResult:
    """Process an item with given options."""
    ...
```

❌ **Forbidden**:
```python
async def process_item(self, item_id, options):  # Missing type hints
    ...
```

## Async/Await Conventions

- All I/O operations MUST be async
- Use `async def` for methods that perform I/O
- Use `await` for all async calls
- Never use blocking I/O in async methods

```python
# Correct
async def fetch_data(self) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(self._url)
        return response.json()
```

## Import Organization

Order imports as follows:
1. Standard library
2. Third-party packages
3. Blueprint framework imports
4. Local application imports

```python
import logging
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent

from blueprint.agents.base import EventHandler
from blueprint.agents.models import HandlerResult

from .models import InvoiceData
from .services import InvoiceService
```

## Docstrings

Use Google-style docstrings for all public methods:

```python
async def process_invoice(self, invoice_id: str) -> InvoiceResult:
    """Process an invoice and extract structured data.

    Args:
        invoice_id: Unique identifier for the invoice

    Returns:
        Structured invoice data with extracted fields

    Raises:
        ValueError: If invoice_id is invalid
        InvoiceNotFoundError: If invoice does not exist
    """
```

## Error Messages

Error messages MUST be descriptive and actionable:

✅ **Good**:
```python
raise ValueError(
    f"Service '{service_name}' not found in registry. "
    f"Available services: {', '.join(available_services)}"
)
```

❌ **Bad**:
```python
raise ValueError("Service not found")
```

## Logging Conventions

Use appropriate log levels:
- `DEBUG` - Detailed diagnostic information
- `INFO` - General informational messages (startup, config loaded)
- `WARNING` - Recoverable issues, deprecated features
- `ERROR` - Errors that don't stop execution
- `CRITICAL` - Fatal errors requiring immediate attention

```python
logger.debug("Processing event: %s", event.type)
logger.info("Handler registered: %s", self.get_name())
logger.warning("Deprecated method called: %s", method_name)
logger.error("Failed to process event: %s", error)
```

## Method Naming

- Use descriptive verb-based names
- Prefix private methods with `_`
- Prefix async methods with action verbs (get, fetch, process, handle)

```python
class InvoiceService(BusinessService):
    async def get_invoice(self, invoice_id: str) -> Invoice:
        """Public async method."""
        return await self._fetch_from_db(invoice_id)
    
    async def _fetch_from_db(self, invoice_id: str) -> Invoice:
        """Private helper method."""
        ...
```

## Constants

Define constants at module level in UPPER_CASE:

```python
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
API_VERSION = "v1"
```

## Pydantic Models

Use Pydantic for all data validation:

```python
from pydantic import BaseModel, Field

class InvoiceRequest(BaseModel):
    """Request model for invoice processing."""
    
    invoice_id: str = Field(..., description="Unique invoice identifier")
    amount: float = Field(..., gt=0, description="Invoice amount")
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
```

## Code Formatting

- Line length: 100 characters maximum
- Use 4 spaces for indentation (no tabs)
- Two blank lines between top-level definitions
- One blank line between methods

## Comments

- Use comments sparingly - prefer self-documenting code
- Explain WHY, not WHAT
- Update comments when code changes

✅ **Good**:
```python
# Retry with exponential backoff to handle transient network errors
await self._retry_with_backoff(operation)
```

❌ **Bad**:
```python
# Call retry method
await self._retry_with_backoff(operation)
```
