"""Health check caching with background refresh using APScheduler."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .....component.namespace import ROOT_LABEL
from .....models.api import ComponentHealth, NamespaceReadiness, ReadinessResponse
from .health_base import HealthCheckEntry
from .namespace_supervisor import NamespaceSupervisor
from .readiness_policy import ReadinessPolicy

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
        *,
        policy: ReadinessPolicy = ReadinessPolicy.ALL,
        supervisor: NamespaceSupervisor | None = None,
    ) -> None:
        """Initialize the health check cache.

        Args:
            check_interval_seconds: How often to refresh health checks (default: 30s)
            initial_status: Initial status while first check runs (default: "UP")
            policy: How a degraded agent affects the pod's readiness (C3). The default
                reproduces what a single-agent application has always done.
            supervisor: Told each agent's verdict after every poll, so it can emit the C7
                signal and stop a degraded agent consuming (C4). Optional so that a test of the
                caching behaviour needs no metrics pipeline and no registry.
        """
        self.check_interval_seconds = check_interval_seconds
        self._scheduler: AsyncIOScheduler | None = None
        self._policy = policy
        self._supervisor = supervisor
        self._cached_response: ReadinessResponse = ReadinessResponse(
            status=initial_status,
            components={},
            policy=policy.value,
        )
        self._last_update: datetime = datetime.now()
        self._lock = asyncio.Lock()
        self._entries: tuple[HealthCheckEntry, ...] = ()

    def set_health_entries(self, entries: Sequence[HealthCheckEntry]) -> None:
        """Set the checks to poll, replacing whatever was set before.

        Entries rather than a ``name -> checker`` mapping because each one carries the agent it
        belongs to as data (see :class:`HealthCheckEntry`). The payload is still keyed by
        ``entry.key``, so nothing about the response shape changes; what is new is that this
        object knows *whose* check each result is, which is what a per-agent readiness policy
        needs (phase 9).

        Args:
            entries: The checks to poll. The whole set, not an addition: ``ActuatorApi``
                accumulates and re-pushes, so this object holds one authoritative list.
        """
        self._entries = tuple(entries)

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
        if not self._entries:
            logger.debug("No health check providers configured")
            return

        try:
            async with self._lock:
                components: dict[str, ComponentHealth] = {}

                # Run all health checks concurrently
                results: list[ComponentHealth | BaseException] = await asyncio.gather(
                    *(entry.checker.health_check() for entry in self._entries), return_exceptions=True
                )

                for entry, result in zip(self._entries, results, strict=True):
                    if isinstance(result, BaseException):
                        # The agent is named separately from the entry key, because that is the
                        # question asked of a group: whose check is failing, not only which one.
                        logger.warning(
                            "Health check '%s' of agent '%s' failed: %s",
                            entry.name,
                            entry.agent,
                            result,
                        )
                        components[entry.key] = ComponentHealth(
                            status="unhealthy",
                            message=f"Check failed: {result}",
                        )
                    else:
                        components[entry.key] = result

                namespace_status, namespaces = self._aggregate_by_agent(components)
                overall_status = "UP" if self._policy.is_ready(namespace_status, self._critical_namespaces()) else "DOWN"

                # Update cache
                self._cached_response = ReadinessResponse(
                    status=overall_status,
                    components=components,
                    policy=self._policy.value,
                    namespaces=namespaces,
                )
                self._last_update = datetime.now()

                logger.debug(
                    "Health checks completed: %s (updated at %s)",
                    overall_status,
                    self._last_update.isoformat(),
                )

            # Outside the lock. The supervisor pauses and resumes transports, which awaits a
            # drain that can take seconds; holding the readiness lock across it would make
            # every probe during a pause wait for it, and a probe that times out is read as a
            # failure of the pod rather than of the one agent that is actually degraded.
            if self._supervisor is not None:
                await self._supervisor.observe(namespace_status)

        except Exception as exc:  # pragma: no cover
            logger.error("Unexpected error during health check refresh: %s", exc, exc_info=True)

    def _critical_namespaces(self) -> frozenset[str]:
        """The agents that gate readiness under the ``critical`` policy, or none known."""
        return self._supervisor.critical_namespaces if self._supervisor is not None else frozenset()

    def _aggregate_by_agent(self, components: dict[str, ComponentHealth]) -> tuple[dict[str, bool], dict[str, NamespaceReadiness]]:
        """Reduce the individual check results to one verdict per agent.

        The agent comes from the entry, not from the key. ``HealthCheckEntry`` carries it as
        data for exactly this reason: recovering it by splitting ``orders.cache:v2.sessions``
        on a separator would attribute that check to an agent called ``orders`` only by luck,
        and to the wrong agent as soon as a name contained the separator -- a C7 violation
        dressed as a string bug.

        Every supervised namespace appears in the result even when it registered no check at
        all. An agent with nothing to check is up, and leaving it out would make ``any`` and
        ``critical`` read a shorter list than the group actually has.

        Args:
            components: This poll's results, keyed by entry key.

        Returns:
            Whether each namespace passed, and the per-agent section of the readiness payload.
        """
        supervised = set(self._supervisor.status) if self._supervisor is not None else set()
        failing: dict[str, list[str]] = {namespace: [] for namespace in supervised}

        for entry in self._entries:
            result = components.get(entry.key)
            failing.setdefault(entry.namespace, [])
            if result is not None and result.status != "healthy":
                failing[entry.namespace].append(entry.key)

        critical = self._critical_namespaces()
        namespace_status = {namespace: not keys for namespace, keys in failing.items()}
        namespaces = {
            (namespace or ROOT_LABEL): NamespaceReadiness(
                status="UP" if not keys else "DOWN",
                # The root is shared infrastructure, so it gates readiness under every policy
                # -- see ReadinessPolicy. Reporting it as critical is what makes the payload
                # explain the verdict rather than contradict it.
                critical=not namespace or namespace in critical,
                failing=keys,
            )
            for namespace, keys in failing.items()
        }
        return namespace_status, namespaces

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
