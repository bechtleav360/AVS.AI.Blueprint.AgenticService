"""Scheduler that performs periodic health checks on all endpoints."""

from __future__ import annotations

import logging

from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase

from src.services.monitor_service import MonitorService

logger = logging.getLogger(__name__)


class HealthCheckScheduler(SchedulerBase):
    """Runs health checks every minute against all configured endpoints."""

    def __init__(self) -> None:
        super().__init__(crontab="*/1 * * * *")
        self._monitor_service: MonitorService | None = None

    async def on_startup(self) -> None:
        """Start the scheduler and resolve MonitorService."""
        await super().on_startup()
        self._monitor_service = self.registry.get_service(MonitorService)  # type: ignore[assignment]
        logger.info("HealthCheckScheduler: monitor service resolved")

    async def on_shutdown(self) -> None:
        """Shut down the scheduler."""
        await super().on_shutdown()

    async def tick(self) -> None:
        """Check all endpoints and store results."""
        if self._monitor_service is None:
            logger.warning("HealthCheckScheduler: monitor service not available")
            return

        logger.info("HealthCheckScheduler: running health checks")
        results = await self._monitor_service.check_all_endpoints()
        for result in results:
            await self._monitor_service.store_result(result)
        logger.info(
            "HealthCheckScheduler: completed %d checks, %d healthy",
            len(results),
            sum(1 for r in results if r.healthy),
        )
