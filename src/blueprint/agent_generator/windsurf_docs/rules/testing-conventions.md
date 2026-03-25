---
trigger: always_on
---

# Testing Conventions and Best Practices

## Test Organization

### Directory Structure

```
tests/
├── unit/                      # Unit tests for individual components
│   ├── test_agent_builder.py
│   ├── test_business_service.py
│   ├── test_event_handler.py
│   └── test_rest_api.py
├── integration/               # Integration tests
│   └── test_full_workflow.py
└── conftest.py               # Shared fixtures
```

### File Naming

- Test files: `test_<module_name>.py`
- Test classes: `Test<ComponentName>`
- Test methods: `test_<behavior>_<expected_result>`

```python
class TestInvoiceService:
    def test_save_invoice_returns_saved_instance(self) -> None:
        ...
    
    def test_get_invoice_returns_none_when_not_found(self) -> None:
        ...
```

## Component Testing Patterns

### BusinessService Testing

Services are plain Python classes - test without framework wiring:

```python
import pytest
from src.services.invoice_service import InvoiceService
from src.models import Invoice

class TestInvoiceService:
    def setup_method(self) -> None:
        self.service = InvoiceService()
    
    @pytest.mark.asyncio
    async def test_save_and_retrieve(self) -> None:
        invoice = Invoice(id="inv-1", amount=100.0)
        saved = await self.service.save(invoice)
        retrieved = await self.service.get("inv-1")
        assert retrieved == saved
    
    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_invoice(self) -> None:
        result = await self.service.get("nonexistent")
        assert result is None
```

### EventHandler Testing

Mock the registry and dependencies:

```python
from unittest.mock import AsyncMock, MagicMock
import pytest
from src.handlers.invoice_handler import InvoiceHandler
from blueprint.agents.models.events import GenericCloudEvent


class TestInvoiceHandler:
    def setup_method(self) -> None:
        self.handler = InvoiceHandler()

        # Mock registry
        registry = MagicMock()
        registry.get_service.return_value = MagicMock()
        registry.get_agent.return_value = AsyncMock()
        self.handler._registry = registry

    @pytest.mark.asyncio
    async def test_can_handle_invoice_event(self) -> None:
        event = GenericCloudEvent(type="invoice.received", data={})
        assert await self.handler.can_handle_event(event, {}) is True

    @pytest.mark.asyncio
    async def test_ignores_other_events(self) -> None:
        event = GenericCloudEvent(type="order.placed", data={})
        assert await self.handler.can_handle_event(event, {}) is False
```

### RestApi Testing

Use FastAPI's TestClient:

```python
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.api.item_api import ItemApi
from src.models import Item


class TestItemApi:
    def setup_method(self) -> None:
        self.api = ItemApi()

        # Mock service
        self.mock_service = MagicMock()
        self.api._service = self.mock_service

        # Create test client
        self.client = TestClient(self.api.router)

    def test_get_item_returns_200_when_found(self) -> None:
        self.mock_service.get.return_value = Item(id="1", name="Test")
        response = self.client.get("/items/1")
        assert response.status_code == 200
        assert response.json()["name"] == "Test"

    def test_get_item_returns_404_when_not_found(self) -> None:
        self.mock_service.get.return_value = None
        response = self.client.get("/items/999")
        assert response.status_code == 404
```

### Scheduler Testing

Test `tick()` directly without starting the asyncio task:

```python
import pytest
from src.schedulers.report_scheduler import DailyReportScheduler

class TestDailyReportScheduler:
    def setup_method(self) -> None:
        self.service = MagicMock()
        self.scheduler = DailyReportScheduler()
        self.scheduler._reports = self.service
    
    @pytest.mark.asyncio
    async def test_tick_generates_report(self) -> None:
        await self.scheduler.tick()
        self.service.generate_daily_report.assert_called_once()
```

## Mocking Best Practices

### Use Appropriate Mock Types

```python
from unittest.mock import MagicMock, AsyncMock, patch

# Sync methods
mock_service = MagicMock()
mock_service.get_config.return_value = {"key": "value"}

# Async methods
mock_agent = AsyncMock()
mock_agent.run.return_value = AgentRunResult(...)

# Patching
@patch("src.services.external_api.httpx.AsyncClient")
async def test_with_patched_client(mock_client):
    ...
```

### Mock Registry Access

```python
def setup_method(self) -> None:
    self.handler = MyHandler()

    # Create mock registry
    registry = MagicMock()
    registry.get_service.return_value = MagicMock(spec=MyService)
    registry.get_agent.return_value = AsyncMock()

    # Link to handler
    self.handler._registry = registry
```

## Fixtures and Reusability

### Shared Fixtures in conftest.py

```python
# tests/conftest.py
import pytest
from blueprint.agents import Config
from pathlib import Path

@pytest.fixture
def test_config():
    """Provide test configuration."""
    return Config(
        settings_files=["tests/fixtures/test_settings.toml"],
        root_path=Path(__file__).parent
    )

@pytest.fixture
def mock_registry():
    """Provide mock component registry."""
    from unittest.mock import MagicMock
    return MagicMock()
```

### Using Fixtures

```python
class TestMyHandler:
    @pytest.mark.asyncio
    async def test_with_config(self, test_config, mock_registry) -> None:
        handler = MyHandler()
        handler._config = test_config
        handler._registry = mock_registry
        ...
```

## Async Testing

### Mark Async Tests

```python
import pytest

@pytest.mark.asyncio
async def test_async_operation() -> None:
    result = await some_async_function()
    assert result is not None
```

### Configure pytest.ini

```ini
[pytest]
asyncio_mode = auto
```

## Test Coverage

### Aim for High Coverage

- **Unit tests**: 80%+ coverage for business logic
- **Integration tests**: Critical workflows
- **Edge cases**: Error handling, validation, boundary conditions

### Run with Coverage

```bash
pytest --cov=src --cov-report=html tests/
```

## Assertions

### Use Descriptive Assertions

✅ **Good**:
```python
assert result.status == "processed", f"Expected 'processed', got '{result.status}'"
assert len(items) == 3, f"Expected 3 items, got {len(items)}"
```

❌ **Bad**:
```python
assert result.status == "processed"  # No context on failure
```

### Use pytest Helpers

```python
import pytest

# Exception testing
with pytest.raises(ValueError, match="Invalid input"):
    service.process("invalid")

# Approximate equality
assert result == pytest.approx(3.14159, rel=1e-5)

# Warnings
with pytest.warns(DeprecationWarning):
    legacy_function()
```

## Test Data

### Use Factories or Builders

```python
from dataclasses import dataclass

@dataclass
class InvoiceBuilder:
    id: str = "inv-1"
    amount: float = 100.0
    currency: str = "USD"
    
    def build(self) -> Invoice:
        return Invoice(
            id=self.id,
            amount=self.amount,
            currency=self.currency
        )

# Usage
invoice = InvoiceBuilder().with_amount(200.0).build()
```

### Avoid Hardcoded Test Data

✅ **Good**:
```python
@pytest.fixture
def sample_invoice():
    return Invoice(id="test-1", amount=100.0)
```

❌ **Bad**:
```python
def test_something():
    invoice = Invoice(id="inv-123", amount=99.99)  # Repeated everywhere
```

## Integration Testing

### Test Full Workflows

```python
@pytest.mark.integration
async def test_invoice_processing_workflow(test_config):
    # Build full application
    app = (
        AppBuilder(test_config)
        .with_service(InvoiceService())
        .with_agent(invoice_agent)
        .with_handler(InvoiceHandler())
        .build()
    )
    
    # Send event
    event = GenericCloudEvent(type="invoice.received", data={"text": "..."})
    result = await app.process_event(event)
    
    # Verify end-to-end
    assert result.status == "processed"
```

## Performance Testing

### Mark Slow Tests

```python
@pytest.mark.slow
async def test_large_batch_processing():
    ...
```

### Run Fast Tests by Default

```bash
# Run only fast tests
pytest -m "not slow"

# Run all tests including slow
pytest
```

## Common Patterns

### Parametrized Tests

```python
@pytest.mark.parametrize("input,expected", [
    ("valid@email.com", True),
    ("invalid-email", False),
    ("", False),
])
def test_email_validation(input, expected):
    assert validate_email(input) == expected
```

### Test Cleanup

```python
class TestWithCleanup:
    def setup_method(self):
        self.temp_file = Path("test.tmp")
    
    def teardown_method(self):
        if self.temp_file.exists():
            self.temp_file.unlink()
```
