"""REST endpoint: the alerts the agent has raised, across all sites."""

from typing import Any

from blueprint.agents.io.api.rest_api_base import RestApiBase

from ..services.reading_service import ReadingService


class AlertApi(RestApiBase):
    """Read-only view of the stored alerts."""

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(ReadingService)

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/alerts", summary="List recent alerts", tags=["Alerts"])
    async def list_alerts(self) -> dict[str, Any]:
        alerts = self._service.recent_alerts()
        return {"count": len(alerts), "alerts": alerts}
