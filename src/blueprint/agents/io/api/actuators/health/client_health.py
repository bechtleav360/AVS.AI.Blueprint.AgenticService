"""Generic health checker for ClientBase-based clients."""

from __future__ import annotations

import logging

from .....clients.client_base import ClientBase
from .....models.api import ComponentHealth
from .health_base import HealthCheckerBase

logger = logging.getLogger(__name__)


class ClientHealthChecker(HealthCheckerBase):
    """Health checker that delegates to one or more ClientBase instances."""

    def __init__(self, clients: list[ClientBase]) -> None:
        self._clients: list[ClientBase] = clients

    async def health_check(self) -> ComponentHealth:
        unhealthy_messages: list[str] = []
        healthy_messages: list[str] = []

        for client in self._clients:
            await client.connect()
            result = await client.health_check()

            if result.status == "healthy":
                healthy_messages.append(result.message)
            else:
                unhealthy_messages.append(result.message)
                logger.warning("Client health check failed: %s", result.message)

        if unhealthy_messages:
            parts = ["Unhealthy: " + "; ".join(unhealthy_messages)]
            if healthy_messages:
                parts.append("Healthy: " + ", ".join(healthy_messages))
            return ComponentHealth(
                status="unhealthy",
                message=" | ".join(parts),
            )

        return ComponentHealth(
            status="healthy",
            message=", ".join(healthy_messages),
        )
