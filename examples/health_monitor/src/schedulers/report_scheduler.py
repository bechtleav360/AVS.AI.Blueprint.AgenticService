"""Scheduler that generates hourly uptime reports."""

from __future__ import annotations

import logging

from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase

from src.services.monitor_service import MonitorService

logger = logging.getLogger(__name__)


class ReportScheduler(SchedulerBase):
    """Generates an uptime report every hour and logs the summary."""

    def __init__(self) -> None:
        super().__init__(crontab="0 * * * *")
        self._monitor_service: MonitorService | None = None

    async def on_startup(self) -> None:
        """Start the scheduler and resolve MonitorService."""
        await super().on_startup()
        self._monitor_service = self.registry.get_service(MonitorService)  # type: ignore[assignment]
        logger.info("ReportScheduler: monitor service resolved")

    async def on_shutdown(self) -> None:
        """Shut down the scheduler."""
        await super().on_shutdown()

    async def tick(self) -> None:
        """Generate and log an uptime report."""
        if self._monitor_service is None:
            logger.warning("ReportScheduler: monitor service not available")
            return

        report = await self._monitor_service.generate_report()
        healthy_count = sum(
            1
            for ep in report.endpoints
            if ep.current_health is not None and ep.current_health.healthy
        )
        logger.info(
            "ReportScheduler: uptime report generated at %s -- %d/%d endpoints healthy, overall_healthy=%s",
            report.generated_at,
            healthy_count,
            len(report.endpoints),
            report.overall_healthy,
        )
        for ep in report.endpoints:
            logger.info(
                "  %s: uptime=%.2f%%, checks=%d, consecutive_failures=%d",
                ep.endpoint_name,
                ep.uptime_percentage,
                ep.total_checks,
                ep.consecutive_failures,
            )
