"""Abstract base class for scheduled background tasks.

Subclasses implement :meth:`tick` and are registered with :class:`AppBuilder`
via ``with_scheduler()``. The scheduler runs via APScheduler and calls
``tick()`` according to the configured crontab expression. A REST endpoint
for manual triggering is registered dynamically under ``/{name}/trigger``
during startup.

Example::

    class CleanupScheduler(SchedulerBase):
        def __init__(self) -> None:
            super().__init__(crontab="0 * * * *")

        async def tick(self) -> None:
            await self.registry.cache_service.clear()
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ....component.component import traced
from ..rest_api_base import RestApiBase

logger = logging.getLogger(__name__)


class SchedulerBase(RestApiBase):
    """Abstract base class for cron-based background schedulers.

    Extends :class:`RestApiBase` so subclasses have access to ``self.registry``,
    ``self.config``, and a REST endpoint for manual triggering.

    The trigger route ``POST /{name}/trigger`` is registered dynamically in
    :meth:`on_startup`, after all ``__init__`` code (including any
    ``self.name`` overrides) has completed.

    Args:
        crontab: Standard cron expression (e.g. ``"*/5 * * * *"``).
    """

    def __init__(self, crontab: str) -> None:
        super().__init__()
        self._crontab = crontab
        self._scheduler: AsyncIOScheduler | None = None

    @abstractmethod
    async def tick(self) -> None:
        """Called on every cron interval.

        Implement your scheduled logic here. Has access to
        ``self.registry`` and ``self.config``.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_startup(self) -> None:
        """Start the APScheduler and register the manual trigger endpoint."""
        trigger = CronTrigger.from_crontab(self._crontab)

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(self.tick, trigger, name=self.name)
        self._scheduler.start()

        self.router.post(
            f"/{self.name}/trigger",
            tags=["Scheduler"],
            summary=f"Manually trigger {self.name}",
        )(self._trigger_tick)

        logger.info("Scheduler '%s' started with crontab '%s'", self.name, self._crontab)

    async def on_shutdown(self) -> None:
        """Shut down APScheduler, waiting for any running tick to finish."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
        logger.info("Scheduler '%s' stopped", self.name)

    # ------------------------------------------------------------------
    # Manual trigger
    # ------------------------------------------------------------------

    @traced()
    async def _trigger_tick(self) -> dict[str, Any]:
        """Manually trigger a tick via REST.

        Returns:
            Status dictionary confirming the trigger.
        """
        logger.info("Scheduler '%s' manually triggered via REST", self.name)
        await self.tick()
        return {"status": "triggered", "scheduler": self.name}
