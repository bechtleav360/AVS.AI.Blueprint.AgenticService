# Scheduler

The `Scheduler` base class lets you run background work on a cron schedule.
Each scheduler runs its own `asyncio` task and has full access to the
`ComponentRegistry` and `Config`.

## Defining a scheduler

```python
from blueprint.agents.base import Scheduler
from .services import ReportService


class DailyReportScheduler(Scheduler):
    def __init__(self) -> None:
        # Standard cron expression: minute hour day month weekday
        super().__init__(crontab="0 6 * * *", name="DailyReportScheduler")

    async def on_startup(self) -> None:
        # Resolve dependencies BEFORE calling super().on_startup()
        # super() starts the asyncio task — tick() may fire immediately
        self._reports: ReportService = self.get_registry().get_service("report_service")
        await super().on_startup()

    async def tick(self) -> None:
        """Called once per cron interval."""
        await self._reports.generate_daily_report()
```

## Crontab syntax

```
┌───────────── minute (0–59)
│ ┌───────────── hour (0–23)
│ │ ┌───────────── day of month (1–31)
│ │ │ ┌───────────── month (1–12)
│ │ │ │ ┌───────────── day of week (0–6, Sunday=0)
│ │ │ │ │
* * * * *
```

Common expressions:

| Expression | Meaning |
|------------|---------|
| `* * * * *` | Every minute |
| `*/5 * * * *` | Every 5 minutes |
| `0 * * * *` | Top of every hour |
| `0 6 * * *` | Every day at 06:00 |
| `0 6 * * 1` | Every Monday at 06:00 |
| `0 0 1 * *` | First day of every month at midnight |

## Registering with AppBuilder

```python
app = (
    AppBuilder(config=config)
    .with_service(ReportService())       # register dependencies first
    .with_scheduler(DailyReportScheduler())
    .build()
)
```

## Multiple schedulers

Each scheduler is independent — register as many as needed:

```python
app = (
    AppBuilder(config=config)
    .with_service(metrics_service)
    .with_scheduler(MetricsCollectorScheduler())   # every minute
    .with_scheduler(CleanupScheduler())            # every hour
    .with_scheduler(DailyReportScheduler())        # daily at 06:00
    .build()
)
```

## Lifecycle

| Phase | What happens |
|-------|-------------|
| `on_startup()` | Called by AppBuilder; resolve dependencies, then `await super().on_startup()` to start the asyncio task |
| `tick()` | Called by the background task on each cron interval |
| `on_shutdown()` | Called by AppBuilder; cancels the asyncio task gracefully |

## Error handling in tick()

Unhandled exceptions in `tick()` are caught by the base class, logged at
`ERROR` level, and the scheduler continues running. You do not need to wrap
`tick()` in a try/except for routine errors, but you should handle domain
errors explicitly:

```python
async def tick(self) -> None:
    try:
        await self._service.do_work()
    except SomeRecoverableError as e:
        logger.warning("Recoverable error in tick: %s", e)
    # RuntimeError / unexpected exceptions are caught by the base class
```

## Sharing data with REST APIs

Schedulers and REST APIs cannot call each other directly. Use a shared
`BusinessService` as the communication channel:

```python
# Scheduler writes
async def tick(self) -> None:
    self._metrics.record("cpu", get_cpu_usage())

# REST API reads
@RestApi.get("/metrics/cpu/summary")
async def cpu_summary(self) -> MetricSummary:
    return self._metrics.get_summary("cpu")
```

## Testing

Test `tick()` directly without starting the asyncio task:

```python
class TestMyScheduler:
    def setup_method(self) -> None:
        self.service = MyService()
        self.scheduler = MyScheduler()
        self.scheduler._my_service = self.service   # inject directly

    @pytest.mark.asyncio
    async def test_tick_does_work(self) -> None:
        await self.scheduler.tick()
        assert self.service.work_done
```
