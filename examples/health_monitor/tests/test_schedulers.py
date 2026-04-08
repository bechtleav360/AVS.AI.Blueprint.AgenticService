"""Unit tests for scheduler tick methods."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.models.schemas import HealthResult, UptimeReport
from src.schedulers.health_check_scheduler import HealthCheckScheduler
from src.schedulers.report_scheduler import ReportScheduler


def _make_health_result(name: str, healthy: bool = True) -> HealthResult:
    return HealthResult(
        endpoint_name=name,
        url=f"https://example.com/{name}",
        status_code=200 if healthy else 500,
        response_time_ms=10.0,
        healthy=healthy,
        error=None,
        checked_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def mock_monitor_service() -> AsyncMock:
    """Create a mock MonitorService with async methods."""
    svc = AsyncMock()
    svc.check_all_endpoints = AsyncMock(
        return_value=[
            _make_health_result("httpbin"),
            _make_health_result("jsonplaceholder"),
        ]
    )
    svc.store_result = AsyncMock()
    svc.generate_report = AsyncMock(
        return_value=UptimeReport(
            generated_at="2026-01-01T00:00:00+00:00",
            endpoints=[],
            overall_healthy=True,
        )
    )
    return svc


class TestHealthCheckScheduler:
    @pytest.mark.asyncio
    async def test_tick_calls_check_and_store(self, mock_monitor_service: AsyncMock) -> None:
        """tick() should call check_all_endpoints and store each result."""
        scheduler = HealthCheckScheduler.__new__(HealthCheckScheduler)
        scheduler._monitor_service = mock_monitor_service

        await scheduler.tick()

        mock_monitor_service.check_all_endpoints.assert_awaited_once()
        assert mock_monitor_service.store_result.await_count == 2

    @pytest.mark.asyncio
    async def test_tick_skips_when_no_service(self) -> None:
        """tick() should log a warning and return if monitor service is not resolved."""
        scheduler = HealthCheckScheduler.__new__(HealthCheckScheduler)
        scheduler._monitor_service = None

        # Should not raise
        await scheduler.tick()


class TestReportScheduler:
    @pytest.mark.asyncio
    async def test_tick_calls_generate_report(self, mock_monitor_service: AsyncMock) -> None:
        """tick() should call generate_report."""
        scheduler = ReportScheduler.__new__(ReportScheduler)
        scheduler._monitor_service = mock_monitor_service

        await scheduler.tick()

        mock_monitor_service.generate_report.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tick_skips_when_no_service(self) -> None:
        """tick() should log a warning and return if monitor service is not resolved."""
        scheduler = ReportScheduler.__new__(ReportScheduler)
        scheduler._monitor_service = None

        # Should not raise
        await scheduler.tick()
