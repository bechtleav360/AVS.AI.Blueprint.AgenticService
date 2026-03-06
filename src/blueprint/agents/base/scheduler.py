"""Abstract base class for scheduled background tasks.

Subclasses implement :meth:`tick` and are registered with :class:`AppBuilder`
via ``with_scheduler()``.  The scheduler runs its own ``asyncio`` background
task and calls ``tick()`` according to the configured crontab expression.

Example::

    class CleanupScheduler(Scheduler):
        def __init__(self) -> None:
            super().__init__(crontab="0 * * * *", name="CleanupScheduler")

        async def tick(self) -> None:
            cache = self.get_registry().get_cache()
            await cache.clear_expired()
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from datetime import datetime, UTC
from typing import TYPE_CHECKING

from croniter import croniter

from .component import Component

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class Scheduler(Component):
    """Abstract base class for cron-based background schedulers.

    Extends :class:`Component` so subclasses have access to
    ``get_registry()`` and ``get_config()`` inside ``tick()``.

    The scheduler runs its own ``asyncio`` background task that sleeps until
    the next cron tick, then calls :meth:`tick`.  The task is started in
    :meth:`on_startup` and cancelled in :meth:`on_shutdown`.

    Args:
        crontab: Standard cron expression (e.g. ``"*/5 * * * *"``).
        name: Human-readable name for the scheduler.
    """

    def __init__(self, crontab: str, name: str = "Scheduler") -> None:
        super().__init__(name)
        self._crontab = crontab
        self._task: asyncio.Task | None = None

    @abstractmethod
    async def tick(self) -> None:
        """Called on every cron interval.

        Implement your scheduled logic here.  The method has access to
        ``self.get_registry()`` and ``self.get_config()``.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_startup(self) -> None:
        """Start the background scheduling task."""
        if not croniter.is_valid(self._crontab):
            raise ValueError(f"Scheduler '{self._component_name}' has an invalid crontab expression: '{self._crontab}'")
        self._task = asyncio.create_task(self._run(), name=f"scheduler.{self._component_name}")
        logger.info("Scheduler '%s' started with crontab '%s'", self._component_name, self._crontab)

    async def on_shutdown(self) -> None:
        """Cancel the background scheduling task."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler '%s' stopped", self._component_name)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Background loop: sleep until next tick, then call tick()."""
        cron = croniter(self._crontab, datetime.now(tz=UTC))
        while True:
            next_dt: datetime = cron.get_next(datetime)
            now = datetime.now(tz=UTC)
            delay = (next_dt - now).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            logger.debug("Scheduler '%s' firing tick", self._component_name)
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "Scheduler '%s' tick raised an unhandled exception: %s",
                    self._component_name,
                    exc,
                )
