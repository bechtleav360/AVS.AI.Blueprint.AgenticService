"""Scheduler that trims old metric snapshots every hour."""

import logging

from blueprint.agents.base import Scheduler

from ..services import MetricsService

logger = logging.getLogger(__name__)

_MAX_SNAPSHOTS_PER_LABEL = 100


class CleanupScheduler(Scheduler):
    """Trims the in-memory metrics store to the most recent 100 snapshots per label.

    Demonstrates a second scheduler running on a different cadence alongside
    the MetricsCollectorScheduler.

    Crontab: ``0 * * * *``  (top of every hour)
    """

    def __init__(self) -> None:
        super().__init__(crontab="0 * * * *", name="CleanupScheduler")

    async def on_startup(self) -> None:
        """Resolve the MetricsService from the registry, then start the task."""
        self._metrics: MetricsService = self.get_registry().get_service("metrics_service")
        await super().on_startup()
        logger.info("CleanupScheduler ready — trimming metrics every hour")

    async def tick(self) -> None:
        """Trim each metric label to the most recent MAX_SNAPSHOTS_PER_LABEL entries."""
        trimmed = 0
        for label in self._metrics.list_labels():
            snapshots = self._metrics._snapshots[label]
            if len(snapshots) > _MAX_SNAPSHOTS_PER_LABEL:
                removed = len(snapshots) - _MAX_SNAPSHOTS_PER_LABEL
                self._metrics._snapshots[label] = snapshots[-_MAX_SNAPSHOTS_PER_LABEL:]
                trimmed += removed

        if trimmed:
            logger.info("CleanupScheduler trimmed %d old metric snapshots", trimmed)
        else:
            logger.info("CleanupScheduler: nothing to trim")
