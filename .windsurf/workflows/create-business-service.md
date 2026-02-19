---
description: Create a new BusinessService subclass for domain logic
---

Ask the user for:
- Service name (e.g. `order_service`)
- Target directory (default: `src/services/`)
- Any other services it depends on

Then follow these steps:

1. Create `src/services/{name}.py`:

```python
"""Domain service for {name}."""

import logging

from blueprint.agents.base import BusinessService

from ..models import {Entity}, {Entity}Request

logger = logging.getLogger(__name__)


class {Name}Service(BusinessService):
    """{Description}.

    Registered in the ComponentRegistry as ``"{name}"``.
    """

    def __init__(self) -> None:
        super().__init__("{name}")
        self._store: dict[str, {Entity}] = {}

    async def on_startup(self) -> None:
        """Optional: connect to DB, load config, etc."""
        logger.info("{Name}Service started")

    async def on_shutdown(self) -> None:
        """Optional: close connections, flush buffers."""

    async def create(self, payload: {Entity}Request) -> {Entity}:
        entity = {Entity}(id=str(len(self._store) + 1), **payload.model_dump())
        self._store[entity.id] = entity
        return entity

    async def get(self, entity_id: str) -> {Entity} | None:
        return self._store.get(entity_id)

    async def list_all(self) -> list[{Entity}]:
        return list(self._store.values())

    async def delete(self, entity_id: str) -> None:
        self._store.pop(entity_id, None)
```

2. Export from `src/services/__init__.py`:

```python
from .{name} import {Name}Service
```

3. Register in `src/main.py` — register dependencies before this service:

```python
from .services import {Name}Service

app = AppBuilder(config=config).with_service({Name}Service()).build()
```

4. Retrieve in other components:

```python
# By type (preferred — gives correct type hint)
service: {Name}Service = self.get_registry().get_service({Name}Service)

# By name
service = self.get_registry().get_service("{name}")
```

## Rules to follow

- The string passed to `super().__init__()` is the registry key — keep it stable, unique, snake_case.
- Never call `get_registry()` or `get_config()` in `__init__`.
- If this service depends on another service, register the dependency first in `AppBuilder`.
- See `docs/windsurf/rules/business-service.md` for the full reference.
