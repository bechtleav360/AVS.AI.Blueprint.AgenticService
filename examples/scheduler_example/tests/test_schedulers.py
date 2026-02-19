"""Unit tests for the scheduler classes."""

import pytest
from unittest.mock import MagicMock

from src.schedulers import CleanupScheduler, MetricsCollectorScheduler
from src.services import MetricsService


class TestMetricsCollectorScheduler:
    """Tests for MetricsCollectorScheduler."""

    def setup_method(self) -> None:
        self.service = MetricsService()
        registry = MagicMock()
        registry.get_service.return_value = self.service

        self.scheduler = MetricsCollectorScheduler()
        self.scheduler._component_registry = registry
        self.scheduler._metrics = self.service

    @pytest.mark.asyncio
    async def test_tick_records_three_metrics(self) -> None:
        await self.scheduler.tick()
        labels = self.service.list_labels()
        assert "cpu_percent" in labels
        assert "memory_percent" in labels
        assert "request_rate" in labels

    @pytest.mark.asyncio
    async def test_tick_increments_counter(self) -> None:
        assert self.scheduler._tick_count == 0
        await self.scheduler.tick()
        assert self.scheduler._tick_count == 1
        await self.scheduler.tick()
        assert self.scheduler._tick_count == 2

    @pytest.mark.asyncio
    async def test_tick_values_in_range(self) -> None:
        for _ in range(10):
            await self.scheduler.tick()

        cpu_summary = self.service.get_summary("cpu_percent")
        assert cpu_summary is not None
        assert 5.0 <= cpu_summary.minimum
        assert cpu_summary.maximum <= 95.0


class TestCleanupScheduler:
    """Tests for CleanupScheduler."""

    def setup_method(self) -> None:
        self.service = MetricsService()
        registry = MagicMock()
        registry.get_service.return_value = self.service

        self.scheduler = CleanupScheduler()
        self.scheduler._component_registry = registry
        self.scheduler._metrics = self.service

    @pytest.mark.asyncio
    async def test_tick_trims_excess_snapshots(self) -> None:
        for i in range(150):
            self.service.record("cpu_percent", float(i))

        assert len(self.service._snapshots["cpu_percent"]) == 150

        await self.scheduler.tick()

        assert len(self.service._snapshots["cpu_percent"]) == 100

    @pytest.mark.asyncio
    async def test_tick_keeps_most_recent(self) -> None:
        for i in range(150):
            self.service.record("cpu_percent", float(i))

        await self.scheduler.tick()

        remaining = self.service._snapshots["cpu_percent"]
        assert remaining[0].value == 50.0
        assert remaining[-1].value == 149.0

    @pytest.mark.asyncio
    async def test_tick_no_op_when_under_limit(self) -> None:
        for i in range(50):
            self.service.record("cpu_percent", float(i))

        await self.scheduler.tick()

        assert len(self.service._snapshots["cpu_percent"]) == 50
