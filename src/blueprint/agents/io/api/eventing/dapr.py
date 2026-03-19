"""Generic Dapr pub/sub endpoints for the agent service (framework-level)."""

import logging
from typing import Any

from fastapi import HTTPException, status

from ....models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from ....clients.io.dapr_client import DaprClient
from ....models import ProcessingStatus
from ....models.events import CloudEvent
from .event_handling_base import EventHandlingBase
from ..rest_api_base import RestApiBase

logger = logging.getLogger(__name__)


class DaprEventing(EventHandlingBase):
    """Encapsulates all Dapr-related endpoints and logic."""

    def __init__(self) -> None:
        super().__init__(should_register=False)
        self._client: DaprClient | None = None

    async def on_startup(self) -> None:
        """Fetch the registered DaprClient from the registry."""
        self._client = self.registry.get_component(DaprClient)

    async def on_shutdown(self) -> None:
        """No shutdown actions required — DaprClient lifecycle is managed separately."""

    @RestApiBase.get("/dapr/subscribe", tags=["dapr"])
    async def subscribe(self, topic: str, queue_group: str | None = None) -> dict[str, Any]:
        """
        Dapr subscription discovery endpoint.

        Implementations can override this by adding their own router with the same
        path to provide real topics and routes.

        Note: this complements subscription resources defined in kubernetes
        (you can choose your approach)

        """

        # Framework default: no subscriptions declared.
        # Example structure:
        # return [
        #     {"pubsubname": "pubsub", "topic": "events.topic1", "route": "/events/topic1"}
        # ]
        return {}

    @RestApiBase.post("/events/{topic}", tags=["dapr"])
    async def publish(self, topic: str, cloud_event: CloudEvent) -> dict[str, Any]:
        """
        Generic Dapr event handler that processes events through the unified service.
        """

        try:
            context = {
                "dapr_topic": topic,
            }

            processing_result = await self._process_cloud_event(cloud_event, context)

            # Return Dapr-compatible response based on result status
            if processing_result.status == ProcessingStatus.PROCESSED:
                return {"status": "SUCCESS"}

            logger.warning(
                "Processing service returned non-success status %s for topic %s",
                processing_result.status.value,
                topic,
            )
            failure_reason = processing_result.message or processing_result.status.value or "unknown_status"
            return {"status": "RETRY", "reason": failure_reason}

        except RetryableHandlerError as exc:
            logger.error(
                "Retrying message for topic %s: %s",
                topic,
                str(exc),
                exc_info=True,
            )
            return {"status": "RETRY", "reason": exc.reason}

        except InvalidEventError as exc:
            logger.error(
                "Dropping message for topic %s: %s",
                topic,
                str(exc),
                exc_info=True,
            )
            return {"status": "DROP", "reason": exc.reason}

        except CriticalHandlerError as exc:
            logger.error(
                "Critical error for topic %s: %s",
                topic,
                str(exc),
                exc_info=True,
            )
            return {"status": "RETRY", "reason": exc.reason}

        except Exception as exc:  # pragma: no cover - integration behaviour
            logger.error(
                "Processing service failed for Dapr topic %s: %s",
                topic,
                str(exc),
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Dapr event handling failed",
            ) from exc

