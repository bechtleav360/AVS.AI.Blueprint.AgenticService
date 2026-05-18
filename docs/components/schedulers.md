# Schedulers

Schedulers run background tasks on a cron-based schedule using APScheduler. They extend RestApiBase, giving them full REST endpoint and registry access in addition to timed execution.

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

The `crontab` parameter accepts a standard five-field cron expression:

```python
super().__init__(crontab="*/5 * * * *")
```

## Cron Expression Reference

A cron expression consists of five fields separated by spaces:

```
┌───────────── minute (0-59)
│ ┌───────────── hour (0-23)
│ │ ┌───────────── day of month (1-31)
│ │ │ ┌───────────── month (1-12)
│ │ │ │ ┌───────────── day of week (0-6, 0 = Sunday)
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
| `0 9 * * 1` | Every Monday at 09:00 |
| `0 0 1 * *` | First day of each month at midnight |
| `0 6,18 * * *` | At 06:00 and 18:00 daily |
| `*/15 9-17 * * 1-5` | Every 15 minutes during business hours, weekdays only |

## Abstract Method: tick

The `tick` method is called on each cron interval. This is where the scheduler's work is performed.

```python
async def tick(self) -> None:
    data = await self._sync_service.fetch_updates()
    await self._sync_service.apply_updates(data)
```

The method must be async. If the work is CPU-bound, offload it to a thread or process pool within the method.

## Lifecycle

SchedulerBase manages the APScheduler lifecycle automatically:

- **on_startup()**: The APScheduler job is created and started. Override this method to resolve service dependencies (call `super().on_startup()` if you override).
- **on_shutdown()**: APScheduler is shut down gracefully, waiting for any in-progress tick to complete.

```python
async def on_startup(self) -> None:
    self._sync_service = self.registry.get_service(SyncService)
    await super().on_startup()  # Starts the APScheduler job

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

This is useful for testing, debugging, and on-demand execution without waiting for the next cron interval.

## Accessing Registry and Config

Since SchedulerBase extends RestApiBase, which extends Component, you have full access to `self.registry` and `self.config` within `tick()`:

```python
async def tick(self) -> None:
    threshold = self.config.get("cleanup_threshold_hours", 24)
    cache = self.registry.cache_service
    await cache.evict_older_than(hours=threshold)
```

## Registration

Register scheduler instances with the application builder. Note that `with_scheduler` receives an instance or a class:

```python
from blueprint.agents import AppBuilder, Config

config = Config()
app = (
    AppBuilder(config)
    .with_scheduler(DataSyncScheduler())
    .build()
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

    async def sync_catalog(self) -> int:
        """Fetch the remote catalog and update the local cache.

        Returns:
            The number of products synchronized.
        """
        assert self._api_client is not None
        assert self._cache is not None

        products = await self._api_client.fetch_product_catalog()
        for product in products:
            await self._cache.set(
                f"product:{product['sku']}",
                product,
                ttl=3600,  # 1 hour TTL
            )

        logger.info("Synchronized %d products", len(products))
        return len(products)

    async def get_product(self, sku: str) -> dict | None:
        """Retrieve a product from cache."""
        assert self._cache is not None
        return await self._cache.get(f"product:{sku}")


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
from blueprint.agents import AppBuilder, Config

config = Config()

app = (
    AppBuilder(config)
    .with_service(ExternalApiClient)
    .with_service(CatalogService)
    .with_scheduler(CatalogSyncScheduler())
    .build()
)
```

With this configuration:

- The `CatalogSyncScheduler.tick()` method runs every 15 minutes.
- Manual triggering is available at `POST /api/catalog_sync_scheduler/trigger`.
- The scheduler delegates all logic to `CatalogService`, which in turn uses `ExternalApiClient` and the cache.

## Testing

Test the scheduler's `tick()` method by mocking the service dependency. The APScheduler internals do not need to be tested directly.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_catalog_service():
    service = AsyncMock()
    service.sync_catalog.return_value = 42
    return service


@pytest.fixture
async def scheduler(mock_catalog_service):
    mock_registry = MagicMock()
    mock_registry.get_service.return_value = mock_catalog_service

    sched = CatalogSyncScheduler()
    sched.registry = mock_registry
    # Resolve dependencies without starting APScheduler
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


@pytest.fixture
def mock_registry_for_integration():
    registry = MagicMock()

    mock_api_client = AsyncMock()
    mock_api_client.fetch_product_catalog.return_value = [
        {"sku": "TEST-1", "price": 10.0, "stock": 5},
    ]

    mock_cache = AsyncMock()
    mock_cache.get.return_value = None

    registry.get_service.side_effect = lambda cls: {
        ExternalApiClient: mock_api_client,
        CatalogService: None,  # Will be created fresh
    }.get(cls)
    registry.cache_service = mock_cache

    return registry
```
