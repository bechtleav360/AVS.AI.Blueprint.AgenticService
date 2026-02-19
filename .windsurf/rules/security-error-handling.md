---
trigger: always_on
---

# Security and Error Handling Standards

## Secure Coding Practices

### API Keys and Secrets

NEVER hardcode secrets in source code:

❌ **Wrong**:
```python
OPENAI_API_KEY = "sk-proj-abc123..."  # NEVER DO THIS
```

✅ **Correct**:
```python
# In settings.toml
[default.runtimes.my_agent]
model_api_key = "@format {env[OPENAI_API_KEY]}"

# In code
api_key = self.get_config().get_ai_config("my_agent").api_key
```

### Input Validation

Always validate external input using Pydantic models:

```python
from pydantic import BaseModel, Field, validator

class UserInput(BaseModel):
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    age: int = Field(..., ge=0, le=150)
    
    @validator("email")
    def validate_email_domain(cls, v: str) -> str:
        if not v.endswith(("@company.com", "@partner.com")):
            raise ValueError("Email must be from allowed domain")
        return v
```

### SQL Injection Prevention

Use parameterized queries, NEVER string concatenation:

❌ **Wrong**:
```python
query = f"SELECT * FROM users WHERE id = {user_id}"  # SQL injection risk
```

✅ **Correct**:
```python
query = "SELECT * FROM users WHERE id = ?"
result = await db.fetch_one(query, user_id)
```

### Path Traversal Prevention

Validate and sanitize file paths:

```python
from pathlib import Path

def load_file(self, filename: str) -> str:
    # Validate filename
    if ".." in filename or filename.startswith("/"):
        raise ValueError("Invalid filename")
    
    # Use Path to prevent traversal
    safe_path = Path(self._base_dir) / filename
    if not safe_path.resolve().is_relative_to(self._base_dir):
        raise ValueError("Path traversal attempt detected")
    
    return safe_path.read_text()
```

## Error Handling

### Exception Hierarchy

Use specific exceptions, not generic ones:

✅ **Good**:
```python
class InvoiceNotFoundError(Exception):
    """Raised when invoice cannot be found."""
    pass

class InvoiceValidationError(Exception):
    """Raised when invoice data is invalid."""
    pass

# Usage
if not invoice:
    raise InvoiceNotFoundError(f"Invoice {invoice_id} not found")
```

❌ **Bad**:
```python
if not invoice:
    raise Exception("Error")  # Too generic
```

### Try-Except Patterns

Handle exceptions at the appropriate level:

```python
async def process_invoice(self, invoice_id: str) -> Invoice:
    """Process invoice with proper error handling."""
    try:
        invoice = await self._fetch_invoice(invoice_id)
        validated = await self._validate_invoice(invoice)
        return await self._save_invoice(validated)
    except InvoiceNotFoundError:
        logger.warning("Invoice not found: %s", invoice_id)
        raise  # Re-raise for caller to handle
    except InvoiceValidationError as e:
        logger.error("Validation failed for %s: %s", invoice_id, e)
        raise
    except Exception as e:
        logger.exception("Unexpected error processing invoice %s", invoice_id)
        raise RuntimeError(f"Failed to process invoice: {e}") from e
```

### Context Managers

Always use context managers for resource cleanup:

```python
# File operations
async def read_config(self, path: str) -> dict:
    async with aiofiles.open(path, "r") as f:
        return json.loads(await f.read())

# HTTP clients
async def fetch_data(self, url: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

# Database connections
async def query_db(self, sql: str) -> list:
    async with self._db_pool.acquire() as conn:
        return await conn.fetch(sql)
```

### Error Recovery

Implement retry logic for transient failures:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def fetch_with_retry(self, url: str) -> dict:
    """Fetch data with automatic retry on transient errors."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
```

## REST API Error Handling

Use FastAPI's HTTPException with proper status codes:

```python
from fastapi import HTTPException, status

@RestApi.get("/items/{item_id}")
async def get_item(self, item_id: str) -> Item:
    try:
        return await self._service.get(item_id)
    except ItemNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found"
        )
    except ItemAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    except Exception as e:
        logger.exception("Unexpected error fetching item %s", item_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
```

## Logging Sensitive Data

NEVER log sensitive information:

❌ **Wrong**:
```python
logger.info("User login: %s, password: %s", username, password)
logger.debug("API key: %s", api_key)
```

✅ **Correct**:
```python
logger.info("User login: %s", username)
logger.debug("API key: %s", api_key[:8] + "..." if api_key else None)
```

## Timeout Configuration

Always set timeouts for external calls:

```python
async def call_external_api(self, endpoint: str) -> dict:
    timeout = httpx.Timeout(
        connect=5.0,  # Connection timeout
        read=30.0,    # Read timeout
        write=10.0,   # Write timeout
        pool=5.0      # Pool timeout
    )
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(endpoint)
        return response.json()
```

## Rate Limiting

Implement rate limiting for external APIs:

```python
from asyncio import Semaphore

class ExternalApiClient:
    def __init__(self) -> None:
        self._semaphore = Semaphore(10)  # Max 10 concurrent requests
    
    async def call_api(self, endpoint: str) -> dict:
        async with self._semaphore:
            async with httpx.AsyncClient() as client:
                response = await client.get(endpoint)
                return response.json()
```
