# Coding Guidelines

General coding standards for this project. These guidelines are assistant-independent —
AI coding assistants should reference this file and apply it without modification.

---

## 1. Architecture & Design

### Object-Oriented Design

Follow strict OOP principles:
- Use classes and inheritance. No module-level functions acting as logic entry points.
- No global variables. Singleton pattern only if absolutely necessary and explicitly justified.
- Encapsulate state within classes.
- Prefer composition over inheritance where appropriate.

### Dependency Injection

**Never instantiate dependencies inside a class.** Resolve them via the registry/container
in lifecycle hooks (e.g. `on_startup()`), not in `__init__`.

✅ **Correct** — resolve in lifecycle hook:
```python
class MyHandler(EventHandler):
    async def on_startup(self) -> None:
        self._service = self.get_registry().get_service(MyService)
        self._agent = self.get_registry().get_agent("my_agent")
```

❌ **Wrong** — direct instantiation:
```python
class MyHandler(EventHandler):
    def __init__(self) -> None:
        self._service = MyService()  # NEVER DO THIS
```

❌ **Wrong** — registry/config access in `__init__`:
```python
class MyHandler(EventHandler):
    def __init__(self) -> None:
        self._service = self.get_registry().get_service(MyService)  # Not linked yet
```

Config and registry are not available until after `__init__` completes. Always defer to
`on_startup()` or lazy-loaded properties.

### Dependency Flow

Dependencies must flow **downward only**:

```
Handlers / APIs / Schedulers
        ↓
    Services
        ↓
  External I/O
```

- Services must not depend on handlers or APIs.
- Agents are self-contained.
- No circular dependencies between modules — use the registry for cross-component access.

### No Global State

- No module-level component instances.
- No singleton patterns (except the application container itself).
- No direct imports between component modules — use the registry.

### Directory Layout

```
src/
├── main.py            # Application wiring ONLY — no business logic
├── api/               # One RestApi subclass per file
├── handlers/          # One EventHandler subclass per file
├── services/          # One BusinessService subclass per file
├── schedulers/        # One Scheduler subclass per file
├── agents/            # Agent builder code
├── models/            # Pydantic models and schemas
└── prompts/           # Prompt files
```

---

## 2. Code Style & Quality

### Type Annotations

Always use complete type hints on every method signature, including `self`-less return types.

✅ **Required**:
```python
async def process_item(self, item_id: str, options: dict[str, Any]) -> ItemResult:
    ...
```

❌ **Forbidden**:
```python
async def process_item(self, item_id, options):  # Missing type hints
    ...
```

### Async / Await

- All I/O operations must be `async def` / `await`.
- Never use blocking I/O (e.g. `open()`, `requests.get()`) inside an async method.
- Use `async with` for all async context managers.

```python
async def fetch_data(self) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.get(self._url)
        return response.json()
```

### Import Organization

Order imports in four groups, separated by blank lines:

```python
# 1. Standard library
import logging
from typing import Any

# 2. Third-party packages
from pydantic import BaseModel
from pydantic_ai import Agent

# 3. Framework imports
from blueprint.agents.base import EventHandler
from blueprint.agents.models import HandlerResult

# 4. Local application imports
from .models import InvoiceData
from .services import InvoiceService
```

### Docstrings

Every public method must have a docstring. For simple methods, a single line is sufficient.
For methods with non-trivial arguments, return values, or error conditions, use Google-style.

```python
def get_name(self) -> str:
    """Return the component's registered name."""
    return self._name

async def process_invoice(self, invoice_id: str) -> InvoiceResult:
    """Process an invoice and extract structured data.

    Args:
        invoice_id: Unique identifier for the invoice.

    Returns:
        Structured invoice data with extracted fields.

    Raises:
        ValueError: If invoice_id is invalid.
        InvoiceNotFoundError: If the invoice does not exist.
    """
```

### Error Messages

Error messages must be descriptive and actionable — include what was expected and what
was actually found.

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

### Logging

Use appropriate log levels:

| Level      | When to use                                          |
|------------|------------------------------------------------------|
| `DEBUG`    | Detailed diagnostic information for developers       |
| `INFO`     | Normal lifecycle events (startup, config loaded)     |
| `WARNING`  | Recoverable issues, deprecated feature usage         |
| `ERROR`    | Errors that don't halt execution                     |
| `CRITICAL` | Fatal errors requiring immediate attention           |

Use `%s`-style format arguments instead of f-strings in log calls. The logger defers
string formatting until the message is actually emitted — if the log level is suppressed,
no formatting work is done at all.

```python
# Correct — formatting deferred
logger.debug("Processing event: %s", event.type)
logger.error("Failed to process %s: %s", invoice_id, error)

# Wrong — formatting always happens, even if DEBUG is suppressed
logger.debug(f"Processing event: {event.type}")
```

### Naming

- Methods: descriptive verb-based names (`get_invoice`, `process_batch`, `handle_event`).
- Private methods and attributes: prefix with `_`.
- Constants: `UPPER_CASE` at module level.

```python
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30.0

class InvoiceService(BusinessService):
    async def get_invoice(self, invoice_id: str) -> Invoice:
        return await self._fetch_from_db(invoice_id)

    async def _fetch_from_db(self, invoice_id: str) -> Invoice:
        ...
```

### Pydantic Models

Use Pydantic for all data validation at system boundaries:

```python
from pydantic import BaseModel, Field

class InvoiceRequest(BaseModel):
    """Request model for invoice processing."""

    invoice_id: str = Field(..., description="Unique invoice identifier")
    amount: float = Field(..., gt=0, description="Invoice amount in the given currency")
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
```

### Formatting

- Maximum line length: **100 characters**
- Indentation: **4 spaces** (no tabs)
- Two blank lines between top-level definitions
- One blank line between methods within a class

### Comments

Comments should explain **why**, not **what**. Self-documenting code is preferred; a
comment that just restates the code adds noise. Keep comments up to date when code changes.

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

---

## 3. Security & Error Handling

### Secrets

Never hardcode API keys, passwords, or tokens in source code.

❌ **Wrong**:
```python
OPENAI_API_KEY = "sk-proj-abc123..."
```

✅ **Correct** — reference via environment variables through the config system:
```toml
# settings.toml
[default.runtimes.my_agent]
model_api_key = "@format {env[OPENAI_API_KEY]}"
```

### Input Validation

Always validate external input (API requests, events, file contents) using Pydantic models
at the system boundary. Never pass raw unvalidated data into business logic.

### SQL Injection

Use parameterized queries. Never concatenate user input into SQL strings.

❌ **Wrong**:
```python
query = f"SELECT * FROM users WHERE id = {user_id}"
```

✅ **Correct**:
```python
query = "SELECT * FROM users WHERE id = ?"
result = await db.fetch_one(query, user_id)
```

### Path Traversal

Validate and resolve file paths before use:

```python
from pathlib import Path

def load_file(self, filename: str) -> str:
    """Load a file safely from the configured base directory."""
    safe_path = (Path(self._base_dir) / filename).resolve()
    if not safe_path.is_relative_to(Path(self._base_dir).resolve()):
        raise ValueError(f"Path traversal attempt detected: {filename}")
    return safe_path.read_text()
```

### Exception Hierarchy

Prefer specific exceptions over generic ones. Define custom domain exceptions when callers
need to distinguish error types programmatically. For simple cases, standard built-ins
(`ValueError`, `KeyError`, `TypeError`) are perfectly appropriate and immediately understood.

```python
# Custom exceptions — use when callers need to catch them specifically
class InvoiceNotFoundError(Exception):
    """Raised when the requested invoice does not exist."""

class InvoiceValidationError(Exception):
    """Raised when invoice data fails business rule validation."""
```

Handle exceptions at the appropriate level and re-raise with context when needed:

```python
async def process_invoice(self, invoice_id: str) -> Invoice:
    """Process invoice with proper error handling."""
    try:
        invoice = await self._fetch_invoice(invoice_id)
        validated = await self._validate_invoice(invoice)
        return await self._save_invoice(validated)
    except InvoiceNotFoundError:
        logger.warning("Invoice not found: %s", invoice_id)
        raise
    except InvoiceValidationError as e:
        logger.error("Validation failed for %s: %s", invoice_id, e)
        raise
    except Exception as e:
        logger.exception("Unexpected error processing invoice %s", invoice_id)
        raise RuntimeError(f"Failed to process invoice: {e}") from e
```

### Resource Cleanup

Always use context managers for files, HTTP clients, and database connections:

```python
async with aiofiles.open(path, "r") as f:
    content = await f.read()

async with httpx.AsyncClient() as client:
    response = await client.get(url)
    response.raise_for_status()

async with self._db_pool.acquire() as conn:
    return await conn.fetch(sql)
```

### Timeouts

Always set explicit timeouts on external calls. An unconfigured timeout means a hung
connection can block a worker indefinitely.

```python
timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
async with httpx.AsyncClient(timeout=timeout) as client:
    response = await client.get(endpoint)
```

### Retry Logic

Use exponential backoff for transient external failures:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def fetch_with_retry(self, url: str) -> dict[str, Any]:
    """Fetch data with automatic retry on transient errors."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
```

### Concurrency Limiting

Use a semaphore to cap the number of simultaneous outbound requests. Note: this limits
**concurrency** (parallel connections), not **rate** (requests per time window). If you
need true rate limiting, use a dedicated library such as `aiolimiter`.

```python
from asyncio import Semaphore

class ExternalApiClient:
    def __init__(self) -> None:
        self._semaphore = Semaphore(10)  # Max 10 simultaneous requests

    async def call_api(self, endpoint: str) -> dict[str, Any]:
        async with self._semaphore:
            async with httpx.AsyncClient() as client:
                response = await client.get(endpoint)
                return response.json()
```

### Sensitive Data in Logs

Never log passwords, full API keys, tokens, or personal data:

❌ **Wrong**:
```python
logger.debug("API key: %s", api_key)
logger.info("User login: %s, password: %s", username, password)
```

✅ **Correct**:
```python
logger.info("User login: %s", username)
logger.debug("API key: %s...", api_key[:8] if api_key else "none")
```

### REST API Error Handling

Map domain exceptions to appropriate HTTP status codes. Never expose internal error
details to external callers.

```python
from fastapi import HTTPException, status

@router.get("/items/{item_id}")
async def get_item(self, item_id: str) -> Item:
    try:
        return await self._service.get(item_id)
    except ItemNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Item {item_id} not found")
    except ItemAccessDeniedError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Access denied")
    except Exception:
        logger.exception("Unexpected error fetching item %s", item_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Internal server error")
```

---

## 4. Testing

### Directory Structure

```
tests/
├── unit/              # Unit tests for individual components
├── integration/       # End-to-end workflow tests
└── conftest.py        # Shared fixtures
```

### Naming Conventions

- Test files: `test_<module_name>.py`
- Test classes: `Test<ComponentName>`
- Test methods: `test_<behavior>_<expected_result>`

```python
class TestInvoiceService:
    def test_save_invoice_returns_saved_instance(self) -> None: ...
    def test_get_invoice_returns_none_when_not_found(self) -> None: ...
```

### Mocking

Use `MagicMock` for synchronous interfaces and `AsyncMock` for async ones. Use `spec=`
to catch attribute errors at test time rather than runtime.

```python
from unittest.mock import AsyncMock, MagicMock

mock_service = MagicMock(spec=MyService)
mock_agent = AsyncMock(spec=MyAgent)
```

When testing components that resolve dependencies via a registry, inject a mock registry
directly onto the private attribute. This is a deliberate trade-off: it couples tests to
the internal attribute name but avoids the need to wire the full application container.

```python
def setup_method(self) -> None:
    self.handler = InvoiceHandler()
    registry = MagicMock()
    registry.get_service.return_value = MagicMock(spec=InvoiceService)
    registry.get_agent.return_value = AsyncMock()
    self.handler._registry = registry
```

### Shared Fixtures

Put reusable setup in `conftest.py`. Prefer `yield` fixtures for teardown over
`setup_method` / `teardown_method` where appropriate.

```python
# tests/conftest.py
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_registry() -> MagicMock:
    """Provide a blank mock component registry."""
    return MagicMock()

@pytest.fixture
def test_config():
    """Provide a test-scoped configuration."""
    return Config(settings_files=["tests/fixtures/test_settings.toml"])
```

### Async Tests

Configure `asyncio_mode = auto` in `pytest.ini` to avoid manually decorating every
async test:

```ini
[pytest]
asyncio_mode = auto
```

### Assertions

Include failure context in assertions so failures are immediately diagnosable:

✅ **Good**:
```python
assert result.status == "processed", f"Expected 'processed', got '{result.status}'"
assert len(items) == 3, f"Expected 3 items, got {len(items)}"
```

Use `pytest.raises` with `match=` to verify both the exception type and message:

```python
with pytest.raises(ValueError, match="Invalid invoice_id"):
    await service.process("")
```

### Test Data

Avoid hardcoded literals scattered across tests. Use fixtures or builder classes to
create test data in one place.

```python
from dataclasses import dataclass, field

@dataclass
class InvoiceBuilder:
    id: str = "inv-1"
    amount: float = 100.0
    currency: str = "USD"

    def with_amount(self, amount: float) -> "InvoiceBuilder":
        self.amount = amount
        return self

    def build(self) -> Invoice:
        return Invoice(id=self.id, amount=self.amount, currency=self.currency)

# Usage
invoice = InvoiceBuilder().with_amount(200.0).build()
```

### Coverage

A minimum of **80% line coverage** is required for business logic. This is a floor to
detect untested code — not a target to chase. Shallow tests written purely to hit a
coverage number are worse than no tests. Prioritize meaningful coverage of business
rules, error handling, and edge cases.

```bash
pytest --cov=src --cov-report=html tests/
```

### Test Categories

Mark slow or integration tests so the fast suite remains quick:

```python
@pytest.mark.slow
async def test_large_batch_processing() -> None: ...

@pytest.mark.integration
async def test_invoice_workflow_end_to_end() -> None: ...
```

```bash
pytest -m "not slow and not integration"   # fast suite (default in CI)
pytest                                      # full suite
```

### Parametrize for Equivalence Classes

```python
@pytest.mark.parametrize("email,expected", [
    ("valid@example.com", True),
    ("invalid-email", False),
    ("", False),
])
def test_email_validation(email: str, expected: bool) -> None:
    assert validate_email(email) == expected
```
