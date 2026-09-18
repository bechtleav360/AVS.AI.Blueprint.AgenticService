# REST APIs

REST APIs define HTTP endpoints using decorator-based routing. Routes are auto-wired during initialization -- there is no manual router setup required.

## Import

```python
from blueprint.agents.io.api.rest_api_base import RestApiBase
```

## Purpose

RestApiBase provides a declarative way to expose HTTP endpoints in a Blueprint Agents application. Each API class groups related endpoints together. The framework auto-discovers decorated methods and registers them with the underlying FastAPI router.

All REST APIs are mounted under the `/api` prefix. A route defined as `/orders` is accessible at `/api/orders`.

APIs should remain thin. Parse the request, call a service, and return the response. All domain logic belongs in services.

## Base Class

```python
from blueprint.agents.io.api.rest_api_base import RestApiBase


class MyApi(RestApiBase):

    def __init__(self) -> None:
        super().__init__()
```

## Route Decorators

Use the static method decorators to define routes. All standard HTTP methods are supported.

### GET

```python
@RestApiBase.get("/items", response_model=list[ItemResponse], tags=["Items"], summary="List all items")
async def list_items(self):
    ...
```

### POST

```python
@RestApiBase.post("/items", response_model=ItemResponse, tags=["Items"], summary="Create an item")
async def create_item(self, request: CreateItemRequest):
    ...
```

### PUT

```python
@RestApiBase.put("/items/{item_id}", response_model=ItemResponse, tags=["Items"], summary="Replace an item")
async def replace_item(self, item_id: str, request: CreateItemRequest):
    ...
```

### DELETE

```python
@RestApiBase.delete("/items/{item_id}", tags=["Items"], summary="Delete an item")
async def delete_item(self, item_id: str):
    ...
```

### PATCH

```python
@RestApiBase.patch("/items/{item_id}", response_model=ItemResponse, tags=["Items"], summary="Update an item")
async def update_item(self, item_id: str, request: PatchItemRequest):
    ...
```

## Decorator Parameters

Each decorator accepts the following keyword arguments:

| Parameter | Type | Description |
|---|---|---|
| `path` | `str` | The URL path (positional). Supports path parameters like `{id}`. |
| `response_model` | `type` | Pydantic model for response serialization and OpenAPI documentation. |
| `tags` | `list[str]` | OpenAPI grouping tags. |
| `summary` | `str` | Short description for OpenAPI documentation. |

## Auto-Wiring

Routes are registered automatically in `__init__`. There is no need to create a router, call `add_api_route`, or perform any manual wiring. Simply decorate your methods and they will be available when the application starts.

## Accessing the Registry

There is an important distinction between accessing the registry during lifecycle hooks and within route methods.

### In on_startup (recommended for service resolution)

```python
async def on_startup(self) -> None:
    self._order_service = self.registry.get_service(OrderService)
```

### In route methods

Within route handler methods, use `self.get_registry()` to access the registry:

```python
@RestApiBase.get("/orders/{order_id}")
async def get_order(self, order_id: str):
    registry = self.get_registry()
    order_service = registry.get_service(OrderService)
    return await order_service.get_order(order_id)
```

The preferred pattern is to resolve services once in `on_startup()` and store them as instance attributes. Use `self.get_registry()` in route methods only when you need lazy or conditional resolution.

## Error Handling

Blueprint Agents includes built-in support for RFC 7807 problem details. When an error occurs, the framework returns a structured JSON response:

```json
{
    "type": "about:blank",
    "title": "Not Found",
    "status": 404,
    "detail": "Order ORD-123 not found",
    "instance": "/api/orders/ORD-123"
}
```

Raise standard HTTP exceptions in your route methods and the framework handles the rest:

```python
from fastapi import HTTPException

@RestApiBase.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(self, order_id: str):
    order = await self._order_service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return order
```

## Registration

Register API instances with the application builder. `with_rest_api` receives an instance or the class:

```python
from blueprint.agents import AppBuilder, Config

config = Config()
app = (
    AppBuilder(config)
    .with_rest_api(OrderApi())
    .with_rest_api(CustomerApi())
    .build()
)
```

## Full Example

```python
from typing import Any
from pydantic import BaseModel
from fastapi import HTTPException
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.services.service_base import ServiceBase


# --- Models ---

class CreateOrderRequest(BaseModel):
    customer_id: str
    items: list[dict[str, Any]]


class OrderResponse(BaseModel):
    order_id: str
    customer_id: str
    total: float
    status: str = "pending"


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]
    count: int


# --- Service (for reference) ---

class OrderService(ServiceBase):
    def __init__(self) -> None:
        super().__init__()

    async def create_order(self, customer_id: str, items: list[dict]) -> dict:
        ...

    async def get_order(self, order_id: str) -> dict | None:
        ...

    async def list_orders(self, customer_id: str | None = None) -> list[dict]:
        ...

    async def cancel_order(self, order_id: str) -> dict:
        ...


# --- API ---

class OrderApi(RestApiBase):
    """HTTP endpoints for order management."""

    def __init__(self) -> None:
        super().__init__()
        self._order_service: OrderService | None = None

    async def on_startup(self) -> None:
        self._order_service = self.registry.get_service(OrderService)

    @RestApiBase.post(
        "/orders",
        response_model=OrderResponse,
        tags=["Orders"],
        summary="Create a new order",
    )
    async def create_order(self, request: CreateOrderRequest):
        assert self._order_service is not None
        order = await self._order_service.create_order(
            customer_id=request.customer_id,
            items=request.items,
        )
        return OrderResponse(**order)

    @RestApiBase.get(
        "/orders",
        response_model=OrderListResponse,
        tags=["Orders"],
        summary="List orders",
    )
    async def list_orders(self, customer_id: str | None = None):
        assert self._order_service is not None
        orders = await self._order_service.list_orders(customer_id)
        return OrderListResponse(
            orders=[OrderResponse(**o) for o in orders],
            count=len(orders),
        )

    @RestApiBase.get(
        "/orders/{order_id}",
        response_model=OrderResponse,
        tags=["Orders"],
        summary="Get order by ID",
    )
    async def get_order(self, order_id: str):
        assert self._order_service is not None
        order = await self._order_service.get_order(order_id)
        if order is None:
            raise HTTPException(
                status_code=404,
                detail=f"Order {order_id} not found",
            )
        return OrderResponse(**order)

    @RestApiBase.delete(
        "/orders/{order_id}",
        tags=["Orders"],
        summary="Cancel an order",
    )
    async def cancel_order(self, order_id: str):
        assert self._order_service is not None
        try:
            result = await self._order_service.cancel_order(order_id)
            return {"message": f"Order {order_id} cancelled", "order": result}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
```

### Application Assembly

```python
from blueprint.agents import AppBuilder, Config

config = Config()
app = (
    AppBuilder(config)
    .with_service(OrderService)
    .with_rest_api(OrderApi())
    .build()
)
```

The endpoints are now available at:

- `POST /api/orders`
- `GET /api/orders`
- `GET /api/orders/{order_id}`
- `DELETE /api/orders/{order_id}`

## Testing

Use FastAPI's `TestClient` or `httpx.AsyncClient` for integration tests. For unit tests, mock the service dependencies directly.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def order_api():
    api = OrderApi()
    mock_registry = MagicMock()

    mock_service = AsyncMock()
    mock_service.create_order.return_value = {
        "order_id": "ORD-001",
        "customer_id": "CUST-1",
        "total": 99.99,
        "status": "pending",
    }
    mock_service.get_order.return_value = {
        "order_id": "ORD-001",
        "customer_id": "CUST-1",
        "total": 99.99,
        "status": "pending",
    }
    mock_service.list_orders.return_value = []

    mock_registry.get_service.return_value = mock_service
    api.registry = mock_registry
    return api


@pytest.mark.asyncio
async def test_create_order(order_api):
    await order_api.on_startup()
    request = CreateOrderRequest(
        customer_id="CUST-1",
        items=[{"sku": "A", "quantity": 1, "unit_price": 99.99}],
    )
    response = await order_api.create_order(request)
    assert response.order_id == "ORD-001"
    assert response.total == 99.99


@pytest.mark.asyncio
async def test_get_order_not_found(order_api):
    await order_api.on_startup()
    order_api._order_service.get_order.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await order_api.get_order("ORD-MISSING")
    assert exc_info.value.status_code == 404
```
