# Testing Guide

This guide covers testing strategies and patterns for Blueprint Agents applications, including unit tests for individual components and integration tests for the full application.

---

## Test Setup

### Dependencies

Blueprint Agents projects use `pytest` with async support. Install the testing dependencies:

```bash
pip install pytest pytest-asyncio pytest-mock httpx
```

### pytest Configuration

Add the following to your `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

Setting `asyncio_mode = "auto"` means all async test functions are automatically recognized as async tests without needing the `@pytest.mark.asyncio` decorator.

### Project Structure

Organize tests to mirror the source layout:

```
tests/
  unit/
    test_handlers.py
    test_services.py
    test_apis.py
    test_agents.py
  integration/
    test_app.py
    test_endpoints.py
  conftest.py
```

---

## Creating a Mock Registry

Many components depend on the service registry to access other services. Create a reusable mock registry fixture in `tests/conftest.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_registry():
    """Create a mock registry with common services pre-configured."""
    registry = MagicMock()
    registry.get_service = MagicMock()

    # Pre-configure commonly needed services
    mock_cache = AsyncMock()
    mock_cache.get = AsyncMock(return_value=None)
    mock_cache.set = AsyncMock()
    registry.get_service.side_effect = lambda name: {
        "cache": mock_cache,
    }.get(name)

    return registry


@pytest.fixture
def mock_cache(mock_registry):
    """Access the mock cache service from the registry."""
    return mock_registry.get_service("cache")
```

To add additional mock services, extend the dictionary in the `side_effect` lambda:

```python
mock_llm = AsyncMock()
mock_llm.generate = AsyncMock(return_value="LLM response")

registry.get_service.side_effect = lambda name: {
    "cache": mock_cache,
    "llm_provider": mock_llm,
}.get(name)
```

---

## Unit Testing Components

### Testing Event Handlers

Event handlers have two key methods to test: `can_handle_event` for routing logic and `handle_event` for processing logic.

```python
# tests/unit/test_handlers.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.handlers.order_processor import OrderProcessorHandler


class TestOrderProcessorHandler:

    @pytest.fixture
    def handler(self, mock_registry):
        handler = OrderProcessorHandler()
        handler.registry = mock_registry
        return handler

    async def test_can_handle_matching_event(self, handler):
        event = {"type": "order.created", "data": {"order_id": "123"}}
        result = await handler.can_handle_event(event)
        assert result is True

    async def test_cannot_handle_non_matching_event(self, handler):
        event = {"type": "user.updated", "data": {}}
        result = await handler.can_handle_event(event)
        assert result is False

    async def test_handle_event_processes_order(self, handler):
        event = {"type": "order.created", "data": {"order_id": "123", "total": 99.99}}
        result = await handler.handle_event(event)
        assert result["status"] == "processed"

    async def test_handle_event_with_missing_data(self, handler):
        event = {"type": "order.created", "data": {}}
        with pytest.raises(ValueError, match="order_id is required"):
            await handler.handle_event(event)
```

### Testing Services

Services typically interact with caches, external APIs, or other services. Mock these dependencies to isolate the service logic.

```python
# tests/unit/test_services.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.pricing_engine import PricingEngineService


class TestPricingEngineService:

    @pytest.fixture
    def service(self, mock_registry):
        svc = PricingEngineService()
        svc.registry = mock_registry
        return svc

    async def test_calculate_price_with_no_cache(self, service, mock_cache):
        mock_cache.get.return_value = None

        result = await service.calculate_price(item_id="abc", quantity=2)

        assert result > 0
        mock_cache.set.assert_called_once()

    async def test_calculate_price_from_cache(self, service, mock_cache):
        mock_cache.get.return_value = {"price": 49.99}

        result = await service.calculate_price(item_id="abc", quantity=1)

        assert result == 49.99
        mock_cache.set.assert_not_called()

    async def test_on_startup_initializes_resources(self, service):
        await service.on_startup()
        # Assert that required resources are initialized
        assert service._initialized is True
```

### Testing REST APIs

Use `httpx.AsyncClient` with the FastAPI test client to test API endpoints without starting a real server.

```python
# tests/unit/test_apis.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from src.api.product_catalog import ProductCatalogApi


class TestProductCatalogApi:

    @pytest.fixture
    def app(self, mock_registry):
        """Create a FastAPI app with the API routes registered."""
        app = FastAPI()
        api = ProductCatalogApi()
        api.registry = mock_registry
        api.register_routes(app.router)
        return app

    @pytest.fixture
    async def client(self, app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    async def test_list_products(self, client):
        response = await client.get("/products")
        assert response.status_code == 200
        data = response.json()
        assert "products" in data

    async def test_create_product(self, client):
        payload = {"name": "Widget", "price": 9.99}
        response = await client.post("/products", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "created"

    async def test_create_product_invalid_payload(self, client):
        response = await client.post("/products", json={})
        assert response.status_code == 422
```

### Testing Agents

When testing components that use an `AgentRuntime`, mock the `agent.run()` method to avoid making real LLM calls.

```python
# tests/unit/test_agents.py
import pytest
from unittest.mock import AsyncMock, patch
from src.services.research_assistant import ResearchAssistantAgent


class TestResearchAssistantAgent:

    @pytest.fixture
    def agent_service(self):
        agent_svc = ResearchAssistantAgent()
        agent_svc.agent = AsyncMock()
        return agent_svc

    async def test_run_returns_response(self, agent_service):
        agent_service.agent.run = AsyncMock(
            return_value="The research findings indicate..."
        )

        result = await agent_service.run("Summarize recent AI trends")

        assert "research findings" in result
        agent_service.agent.run.assert_called_once_with("Summarize recent AI trends")

    async def test_run_handles_empty_prompt(self, agent_service):
        agent_service.agent.run = AsyncMock(return_value="Please provide a query.")

        result = await agent_service.run("")

        assert result == "Please provide a query."

    async def test_run_propagates_runtime_error(self, agent_service):
        agent_service.agent.run = AsyncMock(
            side_effect=RuntimeError("Model unavailable")
        )

        with pytest.raises(RuntimeError, match="Model unavailable"):
            await agent_service.run("test prompt")
```

---

## Integration Testing

Integration tests verify that the full application starts correctly and that endpoints respond as expected.

### Testing the Full Application

```python
# tests/integration/test_app.py
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app


class TestAppIntegration:

    @pytest.fixture
    async def client(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    async def test_health_liveness(self, client):
        response = await client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    async def test_health_readiness(self, client):
        response = await client.get("/health/ready")
        assert response.status_code == 200

    async def test_health_detailed(self, client):
        response = await client.get("/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert "components" in data
```

### Testing Endpoint Behavior

```python
# tests/integration/test_endpoints.py
import pytest
from httpx import AsyncClient, ASGITransport
from src.main import app


class TestEndpoints:

    @pytest.fixture
    async def client(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    async def test_product_lifecycle(self, client):
        # Create a product
        create_response = await client.post(
            "/products", json={"name": "Widget", "price": 9.99}
        )
        assert create_response.status_code == 200

        # Verify it appears in the list
        list_response = await client.get("/products")
        assert list_response.status_code == 200
        products = list_response.json()["products"]
        assert len(products) > 0
```

---

## Running Tests

### Basic Test Execution

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/

# Run a specific test file
pytest tests/unit/test_handlers.py

# Run a specific test class or function
pytest tests/unit/test_handlers.py::TestOrderProcessorHandler::test_can_handle_matching_event
```

### Code Coverage

```bash
# Install coverage plugin
pip install pytest-cov

# Run with coverage report
pytest --cov=src --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=src --cov-report=html
```

### Parallel Test Execution

For larger test suites, run tests in parallel:

```bash
# Install parallel execution plugin
pip install pytest-xdist

# Run tests across multiple CPU cores
pytest -n auto
```

---

## Tips and Best Practices

- **Keep unit tests fast.** Mock all external dependencies including LLM providers, databases, and external APIs. Unit tests should not require network access.
- **Use fixtures liberally.** Define reusable fixtures in `conftest.py` at the appropriate directory level. Fixtures defined in `tests/conftest.py` are available to all tests.
- **Test edge cases.** Verify behavior with empty inputs, missing fields, invalid data types, and error conditions.
- **Name tests descriptively.** Use the pattern `test_<method>_<scenario>_<expected_result>` so test output clearly indicates what failed and why.
- **Separate unit and integration tests.** This allows running fast unit tests during development and slower integration tests in CI pipelines.
