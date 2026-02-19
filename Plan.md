# Implementation Roadmap

## Feature 3 — Streamline base package *(implement first, unblocks 1 & 2)* ✅

- [x] Promote concrete default implementations of `get_name`, `get_registry`, `get_config`,
      `link_config`, `link_component_registry`, `on_startup`, `on_shutdown` into `Component`
      (remove `@abstractmethod`; subclasses only override what is domain-specific)
- [x] Remove the now-redundant overrides from `EventHandler`, `BusinessService`, `RestApi`, `AgentRuntime`
- [x] Delete `interfaces.py` — `ComponentInterface` Protocol is unused everywhere


## Feature 1 — FastAPI annotation-based route registration ✅

Reference: https://fastapi.tiangolo.com/tutorial/bigger-applications/#include-a-path-operation

- [x] `RestApi.__init__` creates an `APIRouter` and auto-discovers route methods via
      inspection: any method decorated with a FastAPI HTTP verb decorator
      (`@router.get`, `@router.post`, …) is registered automatically — no `_register_routes()`
      override needed
- [x] Subclasses annotate methods directly on `self.router` (inherited from `RestApi`);
      the base class wires the router into the FastAPI app via `AppBuilder`
- [x] Remove `payload_type` init param and `Generic[PayloadT]` from `RestApi`
- [x] Remove `_register_routes()` — route registration happens through method decorators
- [x] Update all 4 examples (`rest_microservice`, `complex_agent`, `customer_support_qa`,
      `trivia_game`) to use the annotation pattern


## Feature 2 — Scheduler base class ✅

- [x] Create `src/blueprint/agents/base/scheduler.py` extending `Component`
      - `__init__(self, crontab: str, name: str = "Scheduler")`
      - Abstract method `tick(self) -> None` — called on each cron interval
      - Runs its own `asyncio` background task; uses `croniter` for schedule evaluation
      - Has access to `get_registry()` and `get_config()` via `Component`
- [x] Add `with_scheduler(scheduler: Scheduler)` to `AppBuilder`
- [x] Wire scheduler `on_startup` (start asyncio task) and `on_shutdown` (cancel task)
      into `AppBuilder` lifespan manager
- [x] Export `Scheduler` from `base/__init__.py`
