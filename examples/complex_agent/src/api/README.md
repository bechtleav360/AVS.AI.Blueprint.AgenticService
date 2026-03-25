# Extending the API (REST and Events)

The base framework (`base/src/app.py`) already includes generic routers:

- `base/src/api/rest.py` → mounted at `/api`
- `base/src/api/dapr.py` → Dapr discovery and generic event handler
- `base/src/api/actuators.py` → health and liveness

This `custom/api/` folder is intentionally empty so each agent can add its own endpoints without modifying the base framework.

## How to extend the REST API

1. Create a new router file here, e.g. `orders.py`:

```python
# agent/src/custom/api/orders.py
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.post("/api/orders")
async def create_order(order: dict):
    # TODO: implement domain logic
    return {"status": "created", "order": order}
```

2. Include your router in `agent/src/main.py`:

```python
from fastapi import FastAPI
from base.src.app import create_app
from agent.src.custom.api import orders


def build_app() -> FastAPI:
    app = create_app()
    app.include_router(orders.router, tags=["orders"])  # optionally add prefix
    return app


app = build_app()
```

## How to extend the Events API

1. Create your event router, e.g. `custom_events.py`:

```python
# agent/src/custom/api/custom_events.py
from fastapi import APIRouter

router = APIRouter()

@router.post("/events/asset-created")
async def on_asset_created(event: dict):
    # TODO: implement event handling logic
    return {"status": "processed"}
```

2. Include it in `agent/src/main.py`:

```python
from agent.src.custom.api import custom_events

app.include_router(custom_events.router, tags=["events"])  # prefix already /events in route
```

## How to declare Dapr subscriptions

Override the base discovery endpoint by providing your own router with `GET /dapr/subscribe` and add topic handlers:

```python
# agent/src/custom/api/dapr_subscriptions.py
from typing import Any, Dict, List
from fastapi import APIRouter

router = APIRouter()

@router.get("/dapr/subscribe")
async def dapr_subscribe() -> List[Dict[str, Any]]:
    return [
        {"pubsubname": "pubsub", "topic": "assets.created", "route": "/events/assets.created"},
    ]

@router.post("/events/assets.created")
async def handle_assets_created(event: dict):
    # TODO: handle event
    return {"status": "SUCCESS"}
```

Then wire it in `agent/src/main.py`:

```python
from agent.src.custom.api import dapr_subscriptions

app.include_router(dapr_subscriptions.router, tags=["dapr"])  # mounts subscribe + handlers
```

## Notes

- Keep base framework untouched; all overrides/additions live in `agent/src/custom/api/`.
- Use absolute imports like `from base.src...` to reference framework utilities.
- Tag your routers appropriately for clean API docs.
