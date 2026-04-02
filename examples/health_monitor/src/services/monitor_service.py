"""Health monitoring business service."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import perf_counter

import httpx

from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.services.infrastructure.cache_service import CacheService

from src.models.schemas import EndpointConfig, EndpointStatus, HealthResult, UptimeReport

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "health_monitor"


class MonitorService(ServiceBase):
    """Manages periodic health checks and stores results via cache."""

    def __init__(self) -> None:
        super().__init__()
        self._endpoints: list[EndpointConfig] = []
        self._cache: CacheService | None = None
        self._check_timeout: int = 10

    async def on_startup(self) -> None:
        """Load endpoint configs and resolve cache service."""
        if self.registry.has_cache():
            self._cache = self.registry.cache_service
            logger.info("MonitorService: cache service attached")
        else:
            logger.info("MonitorService: running without cache")

        # Load monitor settings
        monitor_cfg = self.config.get("monitor", {})
        self._check_timeout = monitor_cfg.get("check_timeout_seconds", 10)

        # Load endpoint configurations
        endpoints_cfg = monitor_cfg.get("endpoints", {})
        for name, endpoint_data in endpoints_cfg.items():
            self._endpoints.append(
                EndpointConfig(
                    name=name,
                    url=endpoint_data["url"],
                    interval_seconds=endpoint_data.get("interval_seconds", 60),
                )
            )

        logger.info(
            "MonitorService started with %d endpoints: %s",
            len(self._endpoints),
            [ep.name for ep in self._endpoints],
        )

    async def on_shutdown(self) -> None:
        """Clean up resources."""
        logger.info("MonitorService shutting down")

    async def check_endpoint(self, endpoint: EndpointConfig) -> HealthResult:
        """Perform an HTTP GET against a single endpoint and return the result."""
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            async with httpx.AsyncClient(timeout=self._check_timeout) as client:
                start = perf_counter()
                response = await client.get(endpoint.url)
                elapsed_ms = (perf_counter() - start) * 1000

            healthy = 200 <= response.status_code < 400
            return HealthResult(
                endpoint_name=endpoint.name,
                url=endpoint.url,
                status_code=response.status_code,
                response_time_ms=round(elapsed_ms, 2),
                healthy=healthy,
                error=None,
                checked_at=checked_at,
            )
        except Exception as exc:
            logger.warning("Health check failed for %s: %s", endpoint.name, exc)
            return HealthResult(
                endpoint_name=endpoint.name,
                url=endpoint.url,
                status_code=None,
                response_time_ms=None,
                healthy=False,
                error=str(exc),
                checked_at=checked_at,
            )

    async def check_all_endpoints(self) -> list[HealthResult]:
        """Check all configured endpoints and return results."""
        results: list[HealthResult] = []
        for endpoint in self._endpoints:
            result = await self.check_endpoint(endpoint)
            results.append(result)
        return results

    async def store_result(self, result: HealthResult) -> None:
        """Persist a health-check result and update the endpoint status counters."""
        if self._cache is None:
            return

        status = await self.get_endpoint_status(result.endpoint_name)
        if status is None:
            status = EndpointStatus(
                endpoint_name=result.endpoint_name,
                url=result.url,
            )

        status.current_health = result
        status.total_checks += 1

        if result.healthy:
            status.consecutive_failures = 0
            status.last_healthy = result.checked_at
        else:
            status.consecutive_failures += 1

        # Compute uptime percentage
        successful = self._cache.get(
            f"{result.endpoint_name}:successful_checks",
            namespace=CACHE_NAMESPACE,
        )
        successful_count = (successful or 0) + (1 if result.healthy else 0)
        self._cache.set(
            f"{result.endpoint_name}:successful_checks",
            successful_count,
            namespace=CACHE_NAMESPACE,
        )
        status.uptime_percentage = round((successful_count / status.total_checks) * 100, 2)

        self._cache.set(
            f"status:{result.endpoint_name}",
            status.model_dump(mode="json"),
            namespace=CACHE_NAMESPACE,
        )
        logger.debug(
            "Stored result for %s: healthy=%s, uptime=%.2f%%",
            result.endpoint_name,
            result.healthy,
            status.uptime_percentage,
        )

    async def get_endpoint_status(self, endpoint_name: str) -> EndpointStatus | None:
        """Retrieve the current status for a single endpoint from cache."""
        if self._cache is None:
            return None

        cached = self._cache.get(
            f"status:{endpoint_name}",
            namespace=CACHE_NAMESPACE,
        )
        if cached is None:
            return None
        return EndpointStatus.model_validate(cached)

    async def get_all_statuses(self) -> list[EndpointStatus]:
        """Retrieve the status of all configured endpoints."""
        statuses: list[EndpointStatus] = []
        for endpoint in self._endpoints:
            status = await self.get_endpoint_status(endpoint.name)
            if status is not None:
                statuses.append(status)
            else:
                statuses.append(EndpointStatus(endpoint_name=endpoint.name, url=endpoint.url))
        return statuses

    async def generate_report(self) -> UptimeReport:
        """Generate a full uptime report across all monitored endpoints."""
        statuses = await self.get_all_statuses()
        overall_healthy = all(s.current_health is not None and s.current_health.healthy for s in statuses if s.current_health is not None)
        return UptimeReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            endpoints=statuses,
            overall_healthy=overall_healthy,
        )
