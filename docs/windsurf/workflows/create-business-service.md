---
description: Create a new BusinessService subclass for domain logic
---

## Steps

1. Identify the service name (e.g. `order_service`) and target directory (e.g. `src/services/`).

2. Create `src/services/order_service.py`:

```python
"""Order domain service."""

import logging

from blueprint.agents.base import BusinessService

from ..models import Order, OrderRequest

logger = logging.getLogger(__name__)


class OrderService(BusinessService):
    """Manages order lifecycle.

    Registered in the ComponentRegistry as ``"order_service"``.
    """

    def __init__(self) -> None:
        super().__init__("order_service")
        self._orders: dict[str, Order] = {}

    async def on_startup(self) -> None:
        """Optional: connect to DB, load initial data, etc."""
        logger.info("OrderService started")

    async def on_shutdown(self) -> None:
        """Optional: close connections, flush buffers."""

    async def create(self, payload: OrderRequest) -> Order:
        order = Order(id=str(len(self._orders) + 1), **payload.model_dump())
        self._orders[order.id] = order
        logger.info("Created order %s", order.id)
        return order

    async def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    async def list_all(self) -> list[Order]:
        return list(self._orders.values())

    async def delete(self, order_id: str) -> None:
        self._orders.pop(order_id, None)
```

3. Export from `src/services/__init__.py`:

```python
from .order_service import OrderService
```

4. Register in `src/main.py`:

```python
from .services import OrderService

app = AppBuilder(config=config).with_service(OrderService()).build()
```

5. Retrieve in other components:

```python
# By type (preferred — gives correct type hint)
service: OrderService = self.get_registry().get_service(OrderService)

# By name
service = self.get_registry().get_service("order_service")
```

## Rules

- The string passed to `super().__init__()` is the registry key — keep it stable and unique.
- Never call `get_registry()` or `get_config()` in `__init__`.
- If this service depends on another service, register the dependency first in `AppBuilder`.
- Keep services stateless where possible; use `on_startup()` for one-time initialisation.
