"""In-memory metrics store used by the scheduler and REST API."""

import logging
from collections import defaultdict
from datetime import datetime, timezone

from blueprint.agents.base import BusinessService

from ..models import MetricSnapshot, MetricSummary

logger = logging.getLogger(__name__)


class MetricsService(BusinessService):
    """Stores and aggregates metric snapshots.

    Registered with the component registry under the name ``"metrics_service"``.
    Both the scheduler and the REST API access this service via the registry.
    """

    def __init__(self) -> None:
        super().__init__("metrics_service")
        self._snapshots: dict[str, list[MetricSnapshot]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, label: str, value: float) -> MetricSnapshot:
        """Record a new metric snapshot.

        Args:
            label: Metric label / source identifier
            value: Numeric value to record

        Returns:
            The created MetricSnapshot
        """
        snapshot = MetricSnapshot(
            timestamp=datetime.now(tz=timezone.utc),
            value=value,
            label=label,
        )
        self._snapshots[label].append(snapshot)
        logger.debug("Recorded metric '%s' = %.4f", label, value)
        return snapshot

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_summary(self, label: str) -> MetricSummary | None:
        """Return an aggregated summary for a metric label.

        Args:
            label: Metric label to summarise

        Returns:
            MetricSummary or None if no data has been recorded yet
        """
        snapshots = self._snapshots.get(label)
        if not snapshots:
            return None

        values = [s.value for s in snapshots]
        return MetricSummary(
            label=label,
            count=len(values),
            average=sum(values) / len(values),
            minimum=min(values),
            maximum=max(values),
            last_recorded=snapshots[-1].timestamp,
        )

    def list_labels(self) -> list[str]:
        """Return all known metric labels."""
        return list(self._snapshots.keys())

    def get_recent(self, label: str, limit: int = 10) -> list[MetricSnapshot]:
        """Return the most recent snapshots for a label.

        Args:
            label: Metric label
            limit: Maximum number of snapshots to return

        Returns:
            List of MetricSnapshot (most recent last)
        """
        return list(self._snapshots.get(label, []))[-limit:]
