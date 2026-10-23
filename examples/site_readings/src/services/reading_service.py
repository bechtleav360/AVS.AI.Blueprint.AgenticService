"""Business logic: decide whether a reading is an alert, and keep the alerts for the API."""

import logging
from typing import Any

from blueprint.agents.services.service_base import ServiceBase

from ..models.domain_models import Alert, Reading
from ..sites import current_site

logger = logging.getLogger(__name__)

ALERTS_NAMESPACE = "alerts"


class ReadingService(ServiceBase):
    """Applies the current site's threshold to each reading."""

    async def on_startup(self) -> None:
        self._cache = self.registry.cache_service

    async def on_shutdown(self) -> None:
        pass

    async def on_reading(self, reading: Reading, event_id: str) -> Alert | None:
        """The one method the handler calls. ``None``: the reading is within its site's threshold.

        Safe to run twice for the same event: the alert is stored under the event id, so a
        redelivery overwrites it rather than adding a second one.
        """
        site = current_site()
        if reading.value <= site.alert_threshold:
            return None
        alert = Alert(sensor_id=reading.sensor_id, value=reading.value, threshold=site.alert_threshold, site=site.name)
        self._cache.set(event_id, alert.model_dump(), namespace=ALERTS_NAMESPACE)
        logger.info(
            "Alert at site %s: sensor %s reads %s (threshold %s)", site.name, reading.sensor_id, reading.value, site.alert_threshold
        )
        return alert

    def recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """The stored alerts, for the REST API."""
        return list(self._cache.list_values(namespace=ALERTS_NAMESPACE, limit=limit))
