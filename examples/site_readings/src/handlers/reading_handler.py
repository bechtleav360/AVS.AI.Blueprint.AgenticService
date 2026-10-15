"""The handler for ``reading.recorded``: translate the event, call the service once, translate back."""

from typing import Any

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult

from ..models.domain import Reading
from ..models.schemas import ReadingRecorded
from ..services.reading_service import ReadingService

READING_RECORDED = "reading.recorded"


class ReadingHandler(EventHandlerBase):
    """Knows the subject it consumes (``readings.>``), never the connection or the site it came from."""

    def __init__(self) -> None:
        super().__init__(priority=10)

    async def on_startup(self) -> None:
        self._service = self.registry.get_service(ReadingService)

    async def on_shutdown(self) -> None:
        pass

    def get_subscribed_topics(self) -> list[str]:
        return ["readings.>"]

    def get_handled_event_types(self) -> list[str]:
        return [READING_RECORDED]

    async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
        return event.type == READING_RECORDED

    async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> HandlerResult:
        payload = self.extract_payload(event, ReadingRecorded)
        alert = await self._service.on_reading(Reading(sensor_id=payload.sensor_id, value=payload.value), event_id=event.id)
        if alert is None:
            return HandlerResult.skipped("reading within the site's threshold")
        # No event_type: an agent on named connections does not publish results (named-connections plan, D4).
        return HandlerResult(data=alert.model_dump())
