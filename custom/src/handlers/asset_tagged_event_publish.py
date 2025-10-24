import logging
from typing import Any, Optional
import httpx

from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import HandlerResult

logger = logging.getLogger(__name__)


class HandlerError(Exception):
    """Domain-specific exception raised by handlers."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.code = code or "handler_error"


class AssetHarmonizedEventPublisher(EventHandler):
    """Publishes the harmonized asset entity back to RabbitMQ.

    This handler:
    - Takes the harmonized asset from context (with tags added by AgentInvokerHandler)
    - Publishes it to RabbitMQ via Dapr as 'Asset-Harmonized-Event'
    - Returns the complete enriched Asset Entity

    Event Published:
        - Asset-Harmonized-Event: Complete asset entity with harmonization results
    """

    def __init__(self, dapr_http_port: int = 3500) -> None:
        super().__init__("AssetHarmonizedEventPublisher", priority=40)
        self.dapr_http_port = dapr_http_port
        self.pubsub_name = "rabbitmq-pubsub"
        self.topic_name = "Asset-Harmonized-Event"

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Check if harmonized asset exists in context."""
        if not event.data:
            return False
        return bool(context.get("asset_tagged"))

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Optional[HandlerResult]:
        """Publish harmonized asset back to RabbitMQ."""
        logger.info(
            "AssetHarmonizedEventPublisher processing event '%s'",
            event.type,
        )

        # Get the harmonized asset from context
        asset_tagged = context.get("asset_tagged")
        if not asset_tagged:
            logger.error("No harmonized asset found in context")
            return HandlerResult(
                data={"error": "No harmonized asset in context"},
                event_type="asset.harmonization.error",
                metadata={"reason": "missing_harmonized_asset"},
            )

        # Convert asset to dict if it's a Pydantic model
        if hasattr(asset_tagged, "model_dump"):
            asset_entity = asset_tagged.model_dump()
        elif hasattr(asset_tagged, "dict"):
            asset_entity = asset_tagged.dict()
        else:
            asset_entity = asset_tagged

        # Prepare the event payload matching the schema from the image
        event_payload = {
            "subject": None,
            "data": asset_entity
        }

        # Publish to Dapr
        try:
            url = f"http://localhost:{self.dapr_http_port}/v1.0/publish/{self.pubsub_name}/{self.topic_name}"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=event_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10.0
                )
                
                if response.status_code == 204:
                    logger.info(
                        "Successfully published Asset-Harmonized-Event for asset %s",
                        asset_entity.get("asset_id", "unknown")
                    )
                    return HandlerResult(
                        data={"published": True, "asset_id": asset_entity.get("asset_id")},
                        event_type="asset.harmonized",
                        metadata={
                            "topic": self.topic_name,
                            "status": asset_entity.get("status"),
                        },
                    )
                else:
                    logger.error(
                        "Failed to publish event: %s - %s",
                        response.status_code,
                        response.text
                    )
                    return HandlerResult(
                        data={"error": "Failed to publish"},
                        event_type="asset.harmonization.error",
                        metadata={"status_code": response.status_code},
                    )
        except Exception as e:
            logger.exception("Error publishing harmonized asset: %s", str(e))
            return HandlerResult(
                data={"error": str(e)},
                event_type="asset.harmonization.error",
                metadata={"exception": type(e).__name__},
            )

    def get_published_event_types(self) -> tuple[str, ...]:
        """Declare event types this handler can publish."""
        return (
            "asset.harmonized",
            "asset.harmonization.error",
        )