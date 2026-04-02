"""REST API routes for the Health Monitor status dashboard."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from blueprint.agents.io.api.rest_api_base import RestApiBase

from src.models.schemas import EndpointStatus, UptimeReport
from src.services.monitor_service import MonitorService

logger = logging.getLogger(__name__)


class MonitorApi(RestApiBase):
    """Health monitor status dashboard endpoints."""

    def __init__(self) -> None:
        super().__init__()
        self._monitor_service: MonitorService | None = None

    async def on_startup(self) -> None:
        """Resolve the monitor service from the registry."""
        self._monitor_service = self.registry.get_service(MonitorService)  # type: ignore[assignment]
        logger.info("MonitorApi: monitor service resolved")

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    @property
    def service(self) -> MonitorService:
        """Convenience accessor that raises if called before startup."""
        if self._monitor_service is None:
            raise RuntimeError("MonitorService not resolved yet")
        return self._monitor_service

    @RestApiBase.get(
        "/status",
        response_model=UptimeReport,
        tags=["Health"],
        summary="Get uptime report for all endpoints",
    )
    async def get_status(self) -> UptimeReport:
        """Return a full uptime report across all monitored endpoints."""
        return await self.service.generate_report()

    @RestApiBase.get(
        "/status/{endpoint_name}",
        response_model=EndpointStatus,
        tags=["Health"],
        summary="Get status for a single endpoint",
    )
    async def get_endpoint_status(self, endpoint_name: str) -> EndpointStatus:
        """Return the current status for a single monitored endpoint."""
        status = await self.service.get_endpoint_status(endpoint_name)
        if status is None:
            raise HTTPException(
                status_code=404,
                detail=f"Endpoint '{endpoint_name}' not found or no checks recorded yet",
            )
        return status
