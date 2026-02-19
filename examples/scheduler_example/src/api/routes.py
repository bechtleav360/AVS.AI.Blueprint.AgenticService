"""REST API exposing the collected metrics."""

import logging

from blueprint.agents.base import RestApi
from fastapi import HTTPException

from ..models import MetricSnapshot, MetricSummary
from ..services import MetricsService

logger = logging.getLogger(__name__)


class MetricsRestApi(RestApi):
    """Exposes the metrics collected by the schedulers via HTTP.

    Routes are registered with the ``@RestApi.*`` decorators — no
    ``_register_routes()`` override needed.
    """

    def __init__(self) -> None:
        super().__init__(name="MetricsRestApi")

    async def on_startup(self) -> None:
        """Resolve MetricsService from the component registry."""
        self._metrics: MetricsService = self.get_registry().get_service("metrics_service")

    @RestApi.get("/metrics", response_model=list[str], summary="List all metric labels")
    async def list_metrics(self) -> list[str]:
        """Return all metric labels that have been recorded so far."""
        return self._metrics.list_labels()

    @RestApi.get(
        "/metrics/{label}/summary",
        response_model=MetricSummary,
        summary="Get aggregated summary for a metric",
    )
    async def get_summary(self, label: str) -> MetricSummary:
        """Return min / max / average / count for the given metric label.

        Args:
            label: Metric label (e.g. ``cpu_percent``)
        """
        summary = self._metrics.get_summary(label)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"No data for metric '{label}'")
        return summary

    @RestApi.get(
        "/metrics/{label}/recent",
        response_model=list[MetricSnapshot],
        summary="Get recent snapshots for a metric",
    )
    async def get_recent(self, label: str, limit: int = 10) -> list[MetricSnapshot]:
        """Return the most recent snapshots for a metric label.

        Args:
            label: Metric label
            limit: How many snapshots to return (default 10, max 100)
        """
        limit = min(limit, 100)
        snapshots = self._metrics.get_recent(label, limit)
        if not snapshots:
            raise HTTPException(status_code=404, detail=f"No data for metric '{label}'")
        return snapshots
