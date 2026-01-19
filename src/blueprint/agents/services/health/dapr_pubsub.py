"""Health check provider for Dapr sidecar."""

from __future__ import annotations

import logging

import httpx

from ...config import Config
from ...models.api import ComponentHealth
from .base import HealthCheckerBase

logger = logging.getLogger(__name__)

# Suppress httpx and httpcore INFO logs during health checks
# These loggers emit HTTP request/response details that clutter logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class DaprPubSubHealthChecker(HealthCheckerBase):
    """Health check for Dapr sidecar availability."""

    def __init__(self, config: Config, pubsub_name: str | None = None) -> None:
        self.config: Config = config
        self.enabled: bool = config.get("health_check_dapr", True)
        self.dapr_http_port: int = config.get("dapr_http_port", 3500)
        self.dapr_base_url: str = f"http://localhost:{self.dapr_http_port}"

    async def health_check(self) -> ComponentHealth:
        """Check Dapr sidecar availability.

        This verifies that the Dapr sidecar is reachable and responding to health checks.
        """
        if not self.enabled:
            logger.debug("Dapr health check is disabled")
            return ComponentHealth(
                status="healthy",
                message="Dapr health check disabled",
            )

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Check Dapr sidecar health
                try:
                    dapr_health_response = await client.get(f"{self.dapr_base_url}/v1.0/healthz")
                    dapr_health_response.raise_for_status()

                    return ComponentHealth(
                        status="healthy",
                        message=f"Dapr sidecar reachable at {self.dapr_base_url}",
                    )
                except httpx.RequestError as e:
                    logger.warning("Dapr sidecar not reachable: %s", e)
                    return ComponentHealth(
                        status="unhealthy",
                        message=f"Dapr sidecar unreachable: {e}",
                    )

        except Exception as e:
            logger.error("Unexpected error during Dapr health check: %s", e, exc_info=True)
            return ComponentHealth(
                status="unhealthy",
                message=f"Health check error: {e}",
            )
