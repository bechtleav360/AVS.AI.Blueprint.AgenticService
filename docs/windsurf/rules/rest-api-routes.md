# REST API Route Registration

Routes are registered by decorating **instance methods** with the class-level
HTTP verb decorators provided by `RestApi`. No `_register_routes()` override
is needed.

## Basic pattern

```python
from blueprint.agents.base import RestApi
from fastapi import HTTPException
from .models import ItemRequest, ItemResponse
from .services import ItemService


class ItemApi(RestApi):
    def __init__(self) -> None:
        super().__init__(name="ItemApi")

    async def on_startup(self) -> None:
        self._service: ItemService = self.get_registry().get_service("item_service")

    @RestApi.get("/items", response_model=list[ItemResponse])
    async def list_items(self) -> list[ItemResponse]:
        return await self._service.list()

    @RestApi.post("/items", response_model=ItemResponse, status_code=201)
    async def create_item(self, payload: ItemRequest) -> ItemResponse:
        return await self._service.create(payload)

    @RestApi.get("/items/{item_id}", response_model=ItemResponse)
    async def get_item(self, item_id: str) -> ItemResponse:
        item = await self._service.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return item

    @RestApi.put("/items/{item_id}", response_model=ItemResponse)
    async def update_item(self, item_id: str, payload: ItemRequest) -> ItemResponse:
        return await self._service.update(item_id, payload)

    @RestApi.delete("/items/{item_id}", status_code=204)
    async def delete_item(self, item_id: str) -> None:
        await self._service.delete(item_id)
```

## Available decorators

| Decorator | HTTP method |
|-----------|-------------|
| `@RestApi.get(path, **kwargs)` | GET |
| `@RestApi.post(path, **kwargs)` | POST |
| `@RestApi.put(path, **kwargs)` | PUT |
| `@RestApi.delete(path, **kwargs)` | DELETE |
| `@RestApi.patch(path, **kwargs)` | PATCH |

All keyword arguments are forwarded directly to FastAPI's `APIRouter` method
(e.g. `response_model`, `status_code`, `summary`, `tags`, `dependencies`).

## How it works

`RestApi.__init__` calls `_wire_routes()`, which uses `inspect.getmembers` to
find all methods that carry a `_route` attribute (set by the decorators) and
registers them on `self.router` (a FastAPI `APIRouter`). `AppBuilder` then
calls `app.include_router(api.router)` during `build()`.

## Route method signatures

- The first parameter is always `self`
- Path parameters are declared as function arguments matching the `{name}` in
  the path string
- Request body is declared as a Pydantic model parameter (FastAPI infers it
  automatically)
- Query parameters are plain typed arguments with optional defaults

```python
@RestApi.get("/search", response_model=list[ItemResponse])
async def search(self, q: str, limit: int = 20) -> list[ItemResponse]:
    # q and limit are query parameters
    return await self._service.search(q, limit)
```

## Accessing services inside route methods

Resolve services in `on_startup()` and store them as instance attributes.
Do **not** call `self.get_registry()` inside route handler methods — the
registry call is cheap, but the pattern of resolving once at startup is
cleaner and easier to test:

```python
async def on_startup(self) -> None:
    self._service = self.get_registry().get_service("item_service")
```

## Error handling

Use FastAPI's `HTTPException` for client errors:

```python
from fastapi import HTTPException

raise HTTPException(status_code=404, detail="Not found")
raise HTTPException(status_code=422, detail="Validation failed")
raise HTTPException(status_code=500, detail="Internal error")
```

## Registering with AppBuilder

```python
app = (
    AppBuilder(config=config)
    .with_service(ItemService())
    .with_rest_api(ItemApi())
    .build()
)
```

The router prefix is set by `AppBuilder` based on the application configuration.
All routes from `ItemApi` will be available under that prefix.
