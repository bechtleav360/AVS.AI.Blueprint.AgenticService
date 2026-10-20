# Schedulers

Schedulers run background tasks on a cron schedule. What fires the tick is set by `scheduler_mode`: an external scheduler publishing an event, or an APScheduler timer inside the process (see [Scheduler mode](#scheduler-mode)). They extend RestApiBase, giving them full REST endpoint and registry access in addition to timed execution.

## Import

```python
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase
```

## Purpose

Schedulers handle recurring work such as:

- Periodic data synchronization
- Cache warming and invalidation
- Health checks and watchdog tasks
- Report generation on a fixed cadence
- Cleanup of stale records

Each scheduler defines a cron expression and a `tick()` method that the framework invokes on each interval.

## Base Class

```python
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase


class MyScheduler(SchedulerBase):

    def __init__(self) -> None:
        super().__init__(crontab="*/5 * * * *")  # Every 5 minutes

    async def tick(self) -> None:
        ...
```

## Constructor

The `crontab` parameter accepts a standard five-field cron expression. `topic` (keyword-only, optional) replaces the derived tick subject in event mode -- for ticks already published on a subject someone else owns:

```python
super().__init__(crontab="*/5 * * * *")
super().__init__(crontab="0 2 * * *", topic="ops.nightly.cleanup")
```

The crontab is declared in both modes and checked at startup in both: it must be a valid expression with exactly five fields (no seconds or year field), with the day-of-week rules below.

## Cron Expression Reference

A cron expression consists of five fields separated by spaces:

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (mon-sun; 0-6 = Monday-Sunday)
│ │ │ │ │
* * * * *
```

| Expression | Meaning |
|---|---|
| `* * * * *` | Every minute |
| `*/5 * * * *` | Every 5 minutes |
| `0 * * * *` | Every hour, on the hour |
| `0 */2 * * *` | Every 2 hours |
| `30 9 * * *` | Daily at 09:30 |
| `0 9 * * mon` | Every Monday at 09:00 |
| `0 0 1 * *` | First day of each month at midnight |
| `0 6,18 * * *` | At 06:00 and 18:00 daily |
| `*/15 9-17 * * mon-fri` | Every 15 minutes during business hours, weekdays only |

**The day of the week counts from Monday:** `0` is Monday and `6` is Sunday, as in apscheduler, which
runs the `in_process` timer. A standard cron -- the `CronJob` that fires an `event`-mode tick -- counts
`0` as Sunday, so write days as names (`mon`, `mon-fri`, `sun`), which both read the same. `7` is
refused, and in `event` mode so is any day given by number. The `in_process` timer runs in the
host's local time unless `scheduler_timezone` names one (`"UTC"`, `"Europe/Berlin"`); a value
that is not an IANA timezone name fails startup. In `event` mode the key changes nothing -- the
external scheduler's own timezone decides.

## Scheduler mode

`scheduler_mode` has **no default**: registering a scheduler without it fails at startup, and so
does any value other than the two below (read trimmed and lower-cased, so `"Event"` is accepted).
Which mode is right depends on the deployment -- whether an orchestrator and a broker exist, how
many replicas run -- so the configuration states it. It is read through the agent's own
configuration view, so in a group each agent may set its own.

```toml
[default]
scheduler_mode = "event"        # or "in_process"
```

| Mode | What fires the tick | Needs |
|---|---|---|
| `event` | Something outside the process publishes an event on the scheduler's tick subject. No timer runs in the process. | `event_bus = "nats"` or `"dapr"` |
| `in_process` | An APScheduler timer in every replica, each tick claimed in the cache so one runs it. | `.with_cache()`; Redis when more than one replica runs |

### `event`

The tick arrives as an ordinary event on the subject `<agent>.scheduler.<name>`, where `<agent>`
is the agent's namespace (standalone: `app_name`) and `<name>` the scheduler's own name, without
the agent -- `orders.scheduler.data_sync_scheduler`. `topic=` replaces it. The subject is checked,
not repaired: a namespace, `app_name`, scheduler name or `topic` with whitespace or a wildcard fails
startup, because a rewritten subject would leave the publisher sending to one nobody subscribes to.

The framework registers a tick handler for that subject, so the queue group delivers each tick to
exactly one replica, and deduplication, telemetry and acknowledgement apply as to any event.
**Nothing generates the publisher.** An external scheduler -- a Kubernetes `CronJob`, for
example -- has to publish on that subject on the declared crontab; the crontab in the code is the
contract it follows. An `event_bus` that cannot carry a topic subscription (unset, or `sessions`)
fails startup.

### `in_process`

Every replica's timer fires, and each one claims the tick in the agent's default cache before
running it. The claim key is the scheduler and the minute the tick was scheduled for (in UTC),
held for five minutes; the replica that stores it runs the tick and the others skip it.

**The claim picks one winner across replicas only on Redis.** A disk cache's claim holds within
one process: with a disk cache per pod every replica runs every tick, and replicas sharing one
cache directory (or `uvicorn --workers N` run by hand) can both win a tick. With no cache
declared there is nothing to claim with: every replica runs every tick, and startup logs a
WARNING. A cache that fails while claiming fails open, so the tick runs.

## Abstract Method: tick

The `tick` method is called on each cron interval. This is where the scheduler's work is performed.

```python
async def tick(self) -> None:
    data = await self._sync_service.fetch_updates()
    await self._sync_service.apply_updates(data)
```

The method must be async. If the work is CPU-bound, offload it to a thread or process pool within the method.

## Lifecycle

SchedulerBase manages its lifecycle automatically:

- **on_startup()**: In `in_process` mode the APScheduler job is created and started; in `event` mode no timer starts and the tick waits for its event. Both modes register the `blueprint.scheduler.tick_age_seconds` gauge here. Override this method to resolve service dependencies, and call `super().on_startup()` -- without it the scheduler is registered and never runs.
- **on_shutdown()**: APScheduler, where one runs, is shut down gracefully, waiting for any in-progress tick to complete.

```python
async def on_startup(self) -> None:
    self._sync_service = self.registry.get_service(SyncService)
    await super().on_startup()  # Starts the in_process timer, if that is the mode

async def on_shutdown(self) -> None:
    await super().on_shutdown()  # Waits for in-flight tick, then stops
```

## Manual Trigger Endpoint

Every scheduler automatically exposes a REST endpoint for manual triggering:

```
POST /api/{scheduler_name}/trigger
```

The `scheduler_name` is derived from the class name. For a class named `DataSyncScheduler`, the endpoint would be:

```
POST /api/data_sync_scheduler/trigger
```

In a group, the trigger moves under the agent's reserved `scheduler` segment:
`POST /api/<agent>/scheduler/<name>/trigger`. The name there is the scheduler's own name, without
the agent -- `/api/order/scheduler/data_sync_scheduler/trigger` -- because the path names the agent
already.

This is useful for testing, debugging, and on-demand execution without waiting for the next cron interval. The trigger runs the tick at once in the replica that answers the request, in both modes and without a claim.

## Accessing Registry and Config

Since SchedulerBase extends RestApiBase, which extends Component, you have full access to `self.registry` and `self.config` within `tick()`:

```python
async def tick(self) -> None:
    namespace = self.config.get("report_cache_namespace", "reports")
    cache = self.registry.cache_service   # synchronous: not awaited
    cache.clear(namespace=namespace)
```

## Registration

Register the scheduler with the application builder. Pass the **class** (constructor arguments as keyword arguments) or a zero-argument factory: an already-built instance is refused by a group and by `create_app()`, because it was constructed before its agent's namespace existed:

```python
from blueprint.agents import AppBuilder

agent = (
    AppBuilder()
    .with_scheduler(DataSyncScheduler)
)
```

## Full Example

A scheduler that periodically synchronizes data from an external API and updates the local cache.

```python
import logging
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase
from blueprint.agents.services.service_base import ServiceBase

logger = logging.getLogger(__name__)


# --- Service ---

class ExternalApiClient(ServiceBase):
    """Fetches data from an external system."""

    def __init__(self) -> None:
        super().__init__()
        self._base_url: str = ""

    async def on_startup(self) -> None:
        self._base_url = self.config.get("external_api_url")

    async def on_shutdown(self) -> None:
        pass

    async def fetch_product_catalog(self) -> list[dict]:
        """Retrieve the latest product catalog from the external API."""
        # In production, use httpx or aiohttp here
        return [
            {"sku": "WIDGET-A", "price": 29.99, "stock": 150},
            {"sku": "WIDGET-B", "price": 49.99, "stock": 75},
        ]


class CatalogService(ServiceBase):
    """Manages the local product catalog cache."""

    def __init__(self) -> None:
        super().__init__()
        self._api_client: ExternalApiClient | None = None
        self._cache = None

    async def on_startup(self) -> None:
        self._api_client = self.registry.get_service(ExternalApiClient)
        self._cache = self.registry.cache_service

    async def on_shutdown(self) -> None:
        pass

    async def sync_catalog(self) -> int:
        """Fetch the remote catalog and update the local cache.

        Returns:
            The number of products synchronized.
        """
        assert self._api_client is not None
        assert self._cache is not None

        products = await self._api_client.fetch_product_catalog()
        for product in products:
            self._cache.set(            # the cache is synchronous: not awaited
                f"product:{product['sku']}",
                product,
                ttl=3600,  # 1 hour TTL
            )

        logger.info("Synchronized %d products", len(products))
        return len(products)

    async def get_product(self, sku: str) -> dict | None:
        """Retrieve a product from cache."""
        assert self._cache is not None
        return self._cache.get(f"product:{sku}")


# --- Scheduler ---

class CatalogSyncScheduler(SchedulerBase):
    """Synchronizes the product catalog every 15 minutes."""

    def __init__(self) -> None:
        super().__init__(crontab="*/15 * * * *")
        self._catalog_service: CatalogService | None = None

    async def on_startup(self) -> None:
        self._catalog_service = self.registry.get_service(CatalogService)
        await super().on_startup()

    async def tick(self) -> None:
        assert self._catalog_service is not None

        logger.info("Starting catalog sync")
        try:
            count = await self._catalog_service.sync_catalog()
            logger.info("Catalog sync complete: %d products updated", count)
        except Exception:
            logger.exception("Catalog sync failed")
```

### Application Assembly

```python
from blueprint.agents import AppBuilder

agent = (
    AppBuilder()
    .with_service(ExternalApiClient)
    .with_service(CatalogService)
    .with_scheduler(CatalogSyncScheduler)
)
```

With this configuration:

- The `CatalogSyncScheduler.tick()` method runs every 15 minutes -- fired by the in-process timer or by an external publisher on `<app_name>.scheduler.catalog_sync_scheduler`, as `scheduler_mode` says.
- Manual triggering is available at `POST /api/catalog_sync_scheduler/trigger`.
- The scheduler delegates all logic to `CatalogService`, which in turn uses `ExternalApiClient` and the cache.

## Testing

Test the scheduler's `tick()` method by mocking the service dependency. The APScheduler internals do not need to be tested directly. A component registers itself when it is constructed, so install a mock registry for the test, as the [testing guide](../guides/testing.md) does:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry


@pytest.fixture
def mock_registry():
    """Install a mock registry for every component constructed while the test runs."""
    registry = MagicMock(spec=Registry)
    Component.shared_registry = registry
    yield registry
    Component.reset_shared_state()


@pytest.fixture
def mock_catalog_service():
    service = AsyncMock()
    service.sync_catalog.return_value = 42
    return service


@pytest.fixture
def scheduler(mock_registry, mock_catalog_service):
    sched = CatalogSyncScheduler()
    # Inject the dependency directly instead of running on_startup(), so no timer starts
    sched._catalog_service = mock_catalog_service
    return sched


@pytest.mark.asyncio
async def test_tick_calls_sync(scheduler, mock_catalog_service):
    await scheduler.tick()
    mock_catalog_service.sync_catalog.assert_called_once()


@pytest.mark.asyncio
async def test_tick_handles_errors(scheduler, mock_catalog_service):
    mock_catalog_service.sync_catalog.side_effect = ConnectionError("API down")
    # tick should not propagate the exception
    await scheduler.tick()  # Logs the error, does not raise
```
