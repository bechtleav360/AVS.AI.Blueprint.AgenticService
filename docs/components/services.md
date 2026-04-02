# Services

Services encapsulate all domain and business logic in a Blueprint Agents application. Handlers, APIs, and schedulers should act as thin delegation layers that forward work to services.

## Import

```python
from blueprint.agents.services.service_base import ServiceBase
```

## Purpose

ServiceBase is a thin base class that inherits lifecycle hooks and registry access from Component. Services are the correct location for:

- Business rules and domain logic
- Orchestration across multiple agents or external systems
- Data transformation and validation
- Cache management
- Cross-cutting concerns shared by multiple handlers or APIs

By concentrating logic in services, you keep handlers and APIs simple, and you make domain logic independently testable.

## Base Class

```python
from blueprint.agents.services.service_base import ServiceBase


class MyService(ServiceBase):

    def __init__(self) -> None:
        super().__init__()
```

ServiceBase provides access to `self.registry` and `self.config` inherited from Component. There are no abstract methods to implement -- add whatever public methods your domain requires.

## Lifecycle Hooks

Services participate in the standard component lifecycle:

```python
class MyService(ServiceBase):

    def __init__(self) -> None:
        super().__init__()
        self._db_pool = None

    async def on_startup(self) -> None:
        """Called once when the application starts. Resolve dependencies here."""
        self._db_pool = await create_pool(self.config.get("database_url"))

    async def on_shutdown(self) -> None:
        """Called once when the application shuts down. Release resources here."""
        if self._db_pool:
            await self._db_pool.close()
```

## Accessing the Registry

The registry provides access to other services, agents, and shared infrastructure.

### Other Services

```python
async def on_startup(self) -> None:
    self._auth_service = self.registry.get_service(AuthService)
```

### Agents

```python
async def on_startup(self) -> None:
    self._summarizer = self.registry.get_agent("summarizer")
```

### Cache

```python
async def on_startup(self) -> None:
    self._cache = self.registry.cache_service
```

The cache service is always available once the application has started. Use it for in-memory or distributed caching depending on your deployment configuration.

## Accessing Configuration

Read values from `settings.toml` through `self.config`:

```python
class NotificationService(ServiceBase):

    def __init__(self) -> None:
        super().__init__()
        self._max_retries: int = 3

    async def on_startup(self) -> None:
        self._max_retries = self.config.get("notification_max_retries", 3)
```

## Registration

Register services with the application builder:

```python
from blueprint.agents import AppBuilder, Config

config = Config()
app = (
    AppBuilder(config)
    .with_service(OrderService)
    .with_service(NotificationService)
    .build()
)
```

Note that `with_service` receives the class or an instance.

## Best Practices

1. **Keep handlers and APIs thin.** They should parse input, call a service method, and format the response. All decision-making belongs in services.

2. **Depend on abstractions.** If a service depends on another service, resolve it via the registry in `on_startup()` rather than importing and instantiating directly.

3. **One responsibility per service.** Prefer many small, focused services over a single large one.

4. **Use the cache service for repeated lookups.** Avoid redundant external calls by caching results with appropriate TTLs.

5. **Raise domain exceptions.** Let handlers and APIs translate domain exceptions into the appropriate response format (CloudEvent error, HTTP error).

## Full Example

```python
from typing import Any
from pydantic import BaseModel
from blueprint.agents.services.service_base import ServiceBase


class OrderItem(BaseModel):
    sku: str
    quantity: int
    unit_price: float


class Order(BaseModel):
    order_id: str
    customer_id: str
    items: list[OrderItem]
    total: float = 0.0


class PricingService(ServiceBase):
    """Calculates pricing and discounts."""

    def __init__(self) -> None:
        super().__init__()
        self._discount_threshold: float = 100.0

    async def on_startup(self) -> None:
        self._discount_threshold = self.config.get("discount_threshold", 100.0)

    def calculate_total(self, items: list[OrderItem]) -> float:
        subtotal = sum(item.quantity * item.unit_price for item in items)
        if subtotal >= self._discount_threshold:
            return round(subtotal * 0.9, 2)  # 10% discount
        return round(subtotal, 2)


class OrderService(ServiceBase):
    """Manages order creation and lifecycle."""

    def __init__(self) -> None:
        super().__init__()
        self._pricing: PricingService | None = None
        self._summarizer: Any = None
        self._cache: Any = None

    async def on_startup(self) -> None:
        self._pricing = self.registry.get_service(PricingService)
        self._summarizer = self.registry.get_agent("order_summarizer")
        self._cache = self.registry.cache_service

    async def create_order(self, customer_id: str, items: list[dict]) -> Order:
        """Create a new order with calculated pricing."""
        assert self._pricing is not None

        order_items = [OrderItem(**item) for item in items]
        total = self._pricing.calculate_total(order_items)

        order = Order(
            order_id=self._generate_id(),
            customer_id=customer_id,
            items=order_items,
            total=total,
        )

        # Cache the order for quick retrieval
        if self._cache:
            await self._cache.set(f"order:{order.order_id}", order.model_dump())

        return order

    async def get_order(self, order_id: str) -> Order | None:
        """Retrieve an order, checking cache first."""
        if self._cache:
            cached = await self._cache.get(f"order:{order_id}")
            if cached:
                return Order(**cached)
        return None

    async def summarize_order(self, order: Order) -> str:
        """Use the LLM agent to generate a human-readable summary."""
        assert self._summarizer is not None
        result = await self._summarizer.run(
            f"Summarize this order: {order.model_dump_json()}"
        )
        return result.data

    def _generate_id(self) -> str:
        import uuid
        return f"ORD-{uuid.uuid4().hex[:8].upper()}"
```

## Testing

Services are straightforward to test because they are plain Python classes. Mock the registry and any dependencies.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def pricing_service():
    service = PricingService()
    service.config = MagicMock()
    service.config.get.return_value = 100.0
    return service


@pytest.fixture
async def order_service(pricing_service):
    mock_registry = MagicMock()
    mock_registry.get_service.return_value = pricing_service
    mock_registry.get_agent.return_value = AsyncMock()
    mock_registry.cache_service = AsyncMock()
    mock_registry.cache_service.get.return_value = None

    service = OrderService()
    service.registry = mock_registry
    await pricing_service.on_startup()
    await service.on_startup()
    return service


@pytest.mark.asyncio
async def test_create_order(order_service):
    items = [
        {"sku": "WIDGET-A", "quantity": 2, "unit_price": 25.00},
        {"sku": "WIDGET-B", "quantity": 1, "unit_price": 60.00},
    ]
    order = await order_service.create_order("CUST-1", items)

    assert order.customer_id == "CUST-1"
    assert order.total == 99.0  # 110.00 * 0.9 discount
    assert len(order.items) == 2


@pytest.mark.asyncio
async def test_create_order_no_discount(order_service):
    items = [
        {"sku": "WIDGET-A", "quantity": 1, "unit_price": 10.00},
    ]
    order = await order_service.create_order("CUST-2", items)

    assert order.total == 10.00  # Below threshold, no discount


def test_pricing_calculation(pricing_service):
    items = [
        OrderItem(sku="A", quantity=3, unit_price=50.0),
    ]
    total = pricing_service.calculate_total(items)
    assert total == 135.0  # 150 * 0.9
```
