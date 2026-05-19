"""Unit tests for SchedulerBase."""

from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase


class _TestScheduler(SchedulerBase):
    """Minimal concrete scheduler for testing."""

    tick_call_count: int = 0

    def __init__(self) -> None:
        super().__init__(crontab="*/5 * * * *")
        self.tick_call_count = 0

    async def tick(self) -> None:
        self.tick_call_count += 1

    async def on_startup(self) -> None:
        await super().on_startup()

    async def on_shutdown(self) -> None:
        await super().on_shutdown()


@pytest.fixture
def scheduler(mock_config: MagicMock, mock_registry: MagicMock) -> _TestScheduler:
    """Return a concrete SchedulerBase instance."""
    return _TestScheduler()


class TestTriggerTick:
    async def test_trigger_tick_calls_tick(self, scheduler: _TestScheduler) -> None:
        await scheduler._trigger_tick()
        assert scheduler.tick_call_count == 1

    async def test_trigger_tick_returns_triggered_status(self, scheduler: _TestScheduler) -> None:
        result = await scheduler._trigger_tick()
        assert result["status"] == "triggered"

    async def test_trigger_tick_returns_scheduler_name(self, scheduler: _TestScheduler) -> None:
        result = await scheduler._trigger_tick()
        assert result["scheduler"] == scheduler.name

    async def test_trigger_tick_calls_tick_once_per_call(self, scheduler: _TestScheduler) -> None:
        await scheduler._trigger_tick()
        await scheduler._trigger_tick()
        assert scheduler.tick_call_count == 2


class TestSchedulerOnShutdown:
    async def test_on_shutdown_calls_scheduler_shutdown(self, scheduler: _TestScheduler) -> None:
        mock_sched = MagicMock()
        mock_sched.running = True
        scheduler._scheduler = mock_sched
        await scheduler.on_shutdown()
        mock_sched.shutdown.assert_called_once_with(wait=True)

    async def test_on_shutdown_is_safe_when_scheduler_none(self, scheduler: _TestScheduler) -> None:
        scheduler._scheduler = None
        await scheduler.on_shutdown()  # must not raise

    async def test_on_shutdown_skips_shutdown_when_not_running(self, scheduler: _TestScheduler) -> None:
        mock_sched = MagicMock()
        mock_sched.running = False
        scheduler._scheduler = mock_sched
        await scheduler.on_shutdown()
        mock_sched.shutdown.assert_not_called()


class TestSchedulerOnStartup:
    async def test_on_startup_creates_apscheduler(self, scheduler: _TestScheduler) -> None:
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            await scheduler.on_startup()
        mock_sched_cls.assert_called_once()
        assert scheduler._scheduler is mock_sched

    async def test_on_startup_registers_trigger_endpoint(self, scheduler: _TestScheduler) -> None:
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            await scheduler.on_startup()
        route_paths = [r.path for r in scheduler.router.routes if hasattr(r, "path")]
        assert any(scheduler.name in p for p in route_paths)
