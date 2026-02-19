# Scheduler Example

Demonstrates the `Scheduler` base class from the Blueprint Agents framework.

## What this example shows

| Component | Class | Purpose |
|-----------|-------|---------|
| `MetricsService` | `BusinessService` | In-memory store for metric snapshots |
| `MetricsCollectorScheduler` | `Scheduler` | Collects simulated metrics every minute |
| `CleanupScheduler` | `Scheduler` | Trims old snapshots every hour |
| `MetricsRestApi` | `RestApi` | Exposes collected metrics via HTTP |

Two schedulers run concurrently on different cron schedules. Both access the same
`MetricsService` via `self.get_registry()`. The REST API also reads from the same
service, so HTTP clients can observe the data being collected in real time.

## Project layout

```
scheduler_example/
├── settings.toml
├── pyproject.toml
└── src/
    ├── main.py                          # AppBuilder wiring
    ├── models/
    │   └── schemas.py                   # MetricSnapshot, MetricSummary
    ├── services/
    │   └── metrics_service.py           # MetricsService (BusinessService)
    ├── schedulers/
    │   ├── metrics_collector.py         # Fires every minute  (* * * * *)
    │   └── cleanup_scheduler.py         # Fires every hour   (0 * * * *)
    └── api/
        └── routes.py                    # MetricsRestApi (RestApi)
```

## Running

```bash
# From the examples/scheduler_example directory
uvicorn src.main:app --reload
```

Then open http://localhost:8000/docs to explore the API.

After the first scheduler tick (≤ 1 minute) you can query:

```bash
# List all recorded metric labels
curl http://localhost:8000/metrics

# Get aggregated summary
curl http://localhost:8000/metrics/cpu_percent/summary

# Get 5 most recent snapshots
curl http://localhost:8000/metrics/cpu_percent/recent?limit=5
```

## Running tests

```bash
pytest tests/ -v
```

## Key patterns illustrated

### 1 — Defining a Scheduler

```python
from blueprint.agents.base import Scheduler

class MyScheduler(Scheduler):
    def __init__(self) -> None:
        super().__init__(crontab="*/5 * * * *", name="MyScheduler")

    async def on_startup(self) -> None:
        # Resolve dependencies from the registry BEFORE starting the task
        self._service = self.get_registry().get_service("my_service")
        await super().on_startup()   # starts the asyncio background task

    async def tick(self) -> None:
        await self._service.do_work()
```

> **Important:** Always call `await super().on_startup()` **after** resolving
> dependencies. The base class starts the asyncio task in `on_startup`, so
> `tick()` may fire immediately — your dependencies must be ready first.

### 2 — Registering with AppBuilder

```python
app = (
    AppBuilder(config=config)
    .with_service(my_service)       # register first — schedulers depend on it
    .with_scheduler(MyScheduler())
    .build()
)
```

### 3 — Multiple schedulers

Register as many schedulers as needed. Each runs its own independent asyncio
task and can have a different crontab:

```python
app = (
    AppBuilder(config=config)
    .with_service(metrics_service)
    .with_scheduler(MetricsCollectorScheduler())   # every minute
    .with_scheduler(CleanupScheduler())            # every hour
    .build()
)
```
