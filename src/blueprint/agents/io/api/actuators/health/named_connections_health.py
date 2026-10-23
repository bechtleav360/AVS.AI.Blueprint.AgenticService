"""Readiness of an agent's named NATS connections, under ``nats_connections_readiness`` (named-connections plan, D5)."""

from __future__ import annotations

from .....clients.io.nats_client import NATSClient
from .....models.api import ComponentHealth
from .health_base import HealthCheckerBase


class NamedConnectionsHealthChecker(HealthCheckerBase):
    """Reports every named connection of one agent, and fails only as its readiness mode says.

    Registered with ``affects_consumption=False``: a failure takes the agent out of readiness but
    never pauses it, so a dead tenant connection cannot stop the agent on its other connections.

    - ``never`` (default): always healthy; the message still lists each connection's state.
    - ``any``: healthy while at least one named connection is bound.
    - ``all``: healthy only while every named connection is bound.

    Reads what the client recorded and does no I/O, so a poll never waits on a broker.
    """

    def __init__(self, client: NATSClient) -> None:
        self._client = client

    async def health_check(self) -> ComponentHealth:
        mode = self._client.connections_readiness
        states = self._client.named_connection_states()
        bound = sum(1 for state in states if state.bound)
        if mode == "any":
            healthy = bound > 0
        elif mode == "all":
            healthy = bound == len(states)
        else:
            healthy = True
        listed = ", ".join(state.describe() for state in states) or "none"
        return ComponentHealth(
            status="healthy" if healthy else "unhealthy",
            message=f"{bound}/{len(states)} named connection(s) bound, readiness '{mode}': {listed}",
        )
