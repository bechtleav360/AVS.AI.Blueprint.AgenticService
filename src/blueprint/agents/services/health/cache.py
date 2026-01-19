"""Health check caching with background refresh using APScheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ...models.api import ComponentHealth, ReadinessResponse

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
else:
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        AsyncIOScheduler = None  # type: ignore
        IntervalTrigger = None  # type: ignore

logger = logging.getLogger(__name__)


class HealthCheckCache:
    """Manages health check caching with periodic background updates.

    This class reduces resource consumption by:
    - Caching health check results
    - Running checks periodically in the background
    - Returning cached results immediately to requests
    - Gracefully handling check failures
    """

    def __init__(
        self,
        check_interval_seconds: int = 30,
        initial_status: str = "UP",
    ) -> None:
        """Initialize the health check cache.

        Args:
            check_interval_seconds: How often to refresh health checks (default: 30s)
            initial_status: Initial status while first check runs (default: "UP")
        """
        self.check_interval_seconds = check_interval_seconds
        self._scheduler: AsyncIOScheduler | None = None
        self._cached_response: ReadinessResponse = ReadinessResponse(
            status=initial_status,
            components={},
        )
        self._last_update: datetime = datetime.now()
        self._lock = asyncio.Lock()
        self._health_check_provider: dict[str, Any] | None = None

    def set_health_check_provider(self, provider: dict[str, Any]) -> None:
        """Set the health check provider dependencies.

        Args:
            provider: Dictionary of component_name -> HealthCheckProvider
        """
        self._health_check_provider = provider

    async def start(self) -> None:
        """Start the background health check scheduler."""
        if self._scheduler is not None:
            logger.warning("Health check cache scheduler already running")
            return

        self._scheduler = AsyncIOScheduler()

        # Run initial check immediately
        await self._run_health_checks()

        # Schedule periodic checks
        self._scheduler.add_job(
            self._run_health_checks,
            trigger=IntervalTrigger(seconds=self.check_interval_seconds),
            id="health_check_job",
            name="Periodic health check",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            "Health check cache started with %d second interval",
            self.check_interval_seconds,
        )

    async def stop(self) -> None:
        """Stop the background health check scheduler."""
        if self._scheduler is None:
            return

        self._scheduler.shutdown(wait=False)
        self._scheduler = None
        logger.info("Health check cache stopped")

    async def get_health_status(self) -> ReadinessResponse:
        """Get the cached health status.

        Returns:
            ReadinessResponse with cached health status
        """
        async with self._lock:
            return self._cached_response

    async def _run_health_checks(self) -> None:
        """Run all health checks and update cache."""
        if not self._health_check_provider:
            logger.debug("No health check providers configured")
            return

        try:
            async with self._lock:
                components: dict[str, ComponentHealth] = {}

                # Run all health checks concurrently
                tasks = {name: provider.health_check() for name, provider in self._health_check_provider.items()}

                results: list[ComponentHealth | BaseException] = await asyncio.gather(*tasks.values(), return_exceptions=True)

                for name, result in zip(tasks.keys(), results, strict=True):
                    if isinstance(result, Exception):
                        logger.warning(
                            "Health check failed for %s: %s",
                            name,
                            result,
                        )
                        components[name] = ComponentHealth(
                            status="unhealthy",
                            message=f"Check failed: {result}",
                        )
                    else:
                        components[name] = result

                # Determine overall status
                all_healthy = all(component.status == "healthy" for component in components.values())
                overall_status = "UP" if all_healthy else "DOWN"

                # Update cache
                self._cached_response = ReadinessResponse(
                    status=overall_status,
                    components=components,
                )
                self._last_update = datetime.now()

                logger.debug(
                    "Health checks completed: %s (updated at %s)",
                    overall_status,
                    self._last_update.isoformat(),
                )

        except Exception as exc:  # pragma: no cover
            logger.error("Unexpected error during health check refresh: %s", exc, exc_info=True)

    def get_cache_age_seconds(self) -> float:
        """Get the age of the cached health status in seconds.

        Returns:
            Age of cached status in seconds
        """
        return (datetime.now() - self._last_update).total_seconds()

    def get_cache_info(self) -> dict[str, Any]:
        """Get information about the cache state.

        Returns:
            Dictionary with cache metadata
        """
        return {
            "last_update": self._last_update.isoformat(),
            "age_seconds": self.get_cache_age_seconds(),
            "check_interval_seconds": self.check_interval_seconds,
            "status": self._cached_response.status,
            "components_count": len(self._cached_response.components),
        }
