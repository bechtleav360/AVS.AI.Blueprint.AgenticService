---
description: Create a new RestApi subclass with annotation-based route registration
---

## Steps

1. Identify the feature name (e.g. `orders`) and determine the target directory (e.g. `src/api/`).

2. Create `src/api/orders_api.py` with the following structure:

```python
"""REST API for orders."""

import logging

from blueprint.agents.base import RestApi
from fastapi import HTTPException

from ..models import OrderRequest, OrderResponse
from ..services import OrderService

logger = logging.getLogger(__name__)


class OrdersApi(RestApi):
    """REST API for order management."""

    def __init__(self) -> None:
        super().__init__(name="OrdersApi")

    async def on_startup(self) -> None:
        self._service: OrderService = self.get_registry().get_service("order_service")

    @RestApi.get("/orders", response_model=list[OrderResponse])
    async def list_orders(self) -> list[OrderResponse]:
        return await self._service.list_all()

    @RestApi.post("/orders", response_model=OrderResponse, status_code=201)
    async def create_order(self, payload: OrderRequest) -> OrderResponse:
        return await self._service.create(payload)

    @RestApi.get("/orders/{order_id}", response_model=OrderResponse)
    async def get_order(self, order_id: str) -> OrderResponse:
        order = await self._service.get(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found")
        return order

    @RestApi.delete("/orders/{order_id}", status_code=204)
    async def delete_order(self, order_id: str) -> None:
        await self._service.delete(order_id)
```

3. Export from `src/api/__init__.py`:

```python
from .orders_api import OrdersApi
```

4. Register in `src/main.py`:

```python
from .api import OrdersApi
from .services import OrderService

app = (
    AppBuilder(config=config)
    .with_service(OrderService())
    .with_rest_api(OrdersApi())
    .build()
)
```

5. Verify the routes appear in the OpenAPI docs at `http://localhost:8000/docs`.

## Rules

- The `name` passed to `super().__init__()` must be unique across all registered REST APIs.
- Always resolve services in `on_startup()`, never in `__init__`.
- Use `@RestApi.get/post/put/delete/patch` — never `@self.router.*` directly.
- Each route method must have `self` as the first parameter.
- Path parameters in the URL string (e.g. `{order_id}`) must match the method parameter name exactly.
