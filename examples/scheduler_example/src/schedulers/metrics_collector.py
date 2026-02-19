"""Scheduler that periodically collects simulated system metrics."""

import logging
import random

from blueprint.agents.base import Scheduler

from ..services import MetricsService

logger = logging.getLogger(__name__)


class MetricsCollectorScheduler(Scheduler):
    """Collects simulated CPU, memory, and request-rate metrics every minute.

    Demonstrates how a Scheduler subclass:
    - Accesses a BusinessService via ``self.get_registry()``
    - Runs background work on a cron schedule
    - Keeps its own state between ticks

    Crontab: ``* * * * *``  (every minute)
    """

    def __init__(self) -> None:
        super().__init__(crontab="* * * * *", name="MetricsCollectorScheduler")
        self._tick_count: int = 0

    async def on_startup(self) -> None:
        """Resolve the MetricsService from the registry, then start the task."""
        self._metrics: MetricsService = self.get_registry().get_service("metrics_service")
        await super().on_startup()
        logger.info("MetricsCollectorScheduler ready — collecting every minute")

    async def tick(self) -> None:
        """Simulate collecting CPU %, memory %, and request rate metrics."""
        self._tick_count += 1

        cpu = round(random.uniform(5.0, 95.0), 2)
        memory = round(random.uniform(30.0, 85.0), 2)
        req_rate = round(random.uniform(0.5, 120.0), 2)

        self._metrics.record("cpu_percent", cpu)
        self._metrics.record("memory_percent", memory)
        self._metrics.record("request_rate", req_rate)

        logger.info(
            "Tick #%d — cpu=%.1f%% mem=%.1f%% req_rate=%.1f/s",
            self._tick_count,
            cpu,
            memory,
            req_rate,
        )
