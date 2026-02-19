---
description: Create a new RestApi subclass with annotation-based route registration
---

Ask the user for:
- Feature/resource name (e.g. `orders`)
- Target directory (default: `src/api/`)
- Any services it depends on

Then follow these steps:

1. Create `src/api/{name}_api.py` with this structure:

```python
"""REST API for {name}."""

import logging

from blueprint.agents.base import RestApi
from fastapi import HTTPException

from ..models import {Name}Request, {Name}Response
from ..services import {Name}Service

logger = logging.getLogger(__name__)


class {Name}Api(RestApi):
    """REST API for {name} management."""

    def __init__(self) -> None:
        super().__init__(name="{Name}Api")

    async def on_startup(self) -> None:
        self._service: {Name}Service = self.get_registry().get_service("{name}_service")

    @RestApi.get("/{names}", response_model=list[{Name}Response])
    async def list_{names}(self) -> list[{Name}Response]:
        return await self._service.list_all()

    @RestApi.post("/{names}", response_model={Name}Response, status_code=201)
    async def create_{name}(self, payload: {Name}Request) -> {Name}Response:
        return await self._service.create(payload)

    @RestApi.get("/{names}/{{item_id}}", response_model={Name}Response)
    async def get_{name}(self, item_id: str) -> {Name}Response:
        item = await self._service.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"{Name} '{{item_id}}' not found")
        return item

    @RestApi.delete("/{names}/{{item_id}}", status_code=204)
    async def delete_{name}(self, item_id: str) -> None:
        await self._service.delete(item_id)
```

2. Export from `src/api/__init__.py`:

```python
from .{name}_api import {Name}Api
```

3. Register in `src/main.py`:

```python
from .api import {Name}Api
from .services import {Name}Service

app = (
    AppBuilder(config=config)
    .with_service({Name}Service())
    .with_rest_api({Name}Api())
    .build()
)
```

4. Verify the routes appear in the OpenAPI docs at `http://localhost:8000/docs`.

## Rules to follow

- The `name` passed to `super().__init__()` must be unique across all registered REST APIs.
- Always resolve services in `on_startup()`, never in `__init__`.
- Use `@RestApi.get/post/put/delete/patch` — never `@self.router.*` directly.
- Each route method must have `self` as the first parameter.
- Path parameters in the URL string (e.g. `{item_id}`) must match the method parameter name exactly.
