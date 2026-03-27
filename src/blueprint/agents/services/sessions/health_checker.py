"""Health checker for sessions service connectivity.

This module provides the SessionsServiceHealthChecker that monitors the health
of the sessions service integration, including REST API connectivity and SSE
connection status.
"""

import logging
from datetime import datetime, UTC
from typing import Any

import httpx

from ...models.api import ComponentHealth
from ...io.api.actuators.health.health_base import HealthCheckerBase

logger = logging.getLogger(__name__)


class SessionsServiceHealthChecker(HealthCheckerBase):
    """Health checker for sessions service connectivity.

    Monitors:
    - REST API connectivity
    - SSE connection status (via heartbeat tracking)
    - Last heartbeat timestamp

    The JobConsumerService should call update_heartbeat() when SSE heartbeat
    events are received to keep the health status current.
    """

    def __init__(self, base_url: str, api_key: str):
        """Initialize the health checker.

        Args:
            base_url: Base URL of sessions service
            api_key: API key for authentication
        """
        self._base_url = base_url
        self._api_key = api_key
        self._last_heartbeat: datetime | None = None

    async def health_check(self) -> ComponentHealth:
        """Check sessions service health.

        Returns:
            ComponentHealth with status and details
        """
        details: dict[str, Any] = {}

        # Check REST API connectivity
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._base_url}/health",
                    headers={"X-Api-Key": self._api_key},
                    timeout=5.0,
                )
                response.raise_for_status()
                details["rest_api"] = "connected"
        except Exception as e:
            logger.error("Sessions service REST API health check failed: %s", e)
            return ComponentHealth(
                status="DOWN",
                message=f"REST API unreachable: {str(e)}",
                details={"rest_api": "disconnected", "error": str(e)},
            )

        # Check SSE connection status via heartbeat
        if self._last_heartbeat:
            time_since_heartbeat = (datetime.now(UTC) - self._last_heartbeat).total_seconds()
            details["last_heartbeat_seconds_ago"] = int(time_since_heartbeat)

            # Consider stale if no heartbeat in 60 seconds
            if time_since_heartbeat < 60:
                details["sse_connection"] = "active"
                return ComponentHealth(
                    status="UP",
                    message="Sessions service healthy",
                    details=details,
                )
            else:
                details["sse_connection"] = "stale"
                return ComponentHealth(
                    status="DOWN",
                    message=f"SSE connection stale (last heartbeat {int(time_since_heartbeat)}s ago)",
                    details=details,
                )
        else:
            # No heartbeat received yet
            details["sse_connection"] = "unknown"
            details["last_heartbeat_seconds_ago"] = None
            return ComponentHealth(
                status="UP",
                message="Sessions service REST API healthy, SSE status unknown",
                details=details,
            )

    def update_heartbeat(self) -> None:
        """Update the last heartbeat timestamp.

        Should be called by JobConsumerService when SSE heartbeat events are received.
        """
        self._last_heartbeat = datetime.now(UTC)
        logger.debug("Sessions service heartbeat updated")
