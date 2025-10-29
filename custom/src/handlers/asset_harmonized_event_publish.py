import logging
from typing import Any, Optional

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
    - Takes the harmonized asset from context (result added by AgentInvokerHandler)
    - Determines event type based on harmonization status
    - Returns a structured HandlerResult for publishing

    Event Published:
        - asset.harmonized / asset.not_harmonized / asset.harmonization.error
    """

    def __init__(self, dapr_http_port: int = 3500) -> None:
        super().__init__("AssetHarmonizedEventPublisher", priority=40)

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Check if required context exists (asset and harmonization result)."""
        if not event.data:
            return False
        return bool(context.get("asset_harmonized")) and bool(context.get("asset_fetched"))

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Optional[HandlerResult]:
        """Decide event type based on harmonization result and return it for publishing."""
        logger.info(
            "AssetHarmonizedEventPublisher processing event '%s'",
            event.type,
        )

        asset = context.get("asset_fetched")
        if not asset or not isinstance(asset, dict):
            raise HandlerError(status="invalid", reason="No asset in context to update harmonization result")

        asset_id = asset.get("id")
        if not asset_id:
            raise HandlerError(status="invalid", reason="Asset ID missing for harmonization update")

        asset_harmonized = context.get("asset_harmonized")
        if not asset_harmonized:
            raise HandlerError(status="invalid", reason="No harmonization result available")

        # Determine event type based on harmonization validation status
        status_lower = getattr(asset_harmonized, "status", "").lower()
        if status_lower == "valid":
            event_type = "asset.harmonized"
            logger.info("Asset %s is harmonized successfully", asset_id)
        elif status_lower in ["invalid", "incomplete"]:
            event_type = "asset.not_harmonized"
            logger.warning("Asset %s harmonization is INVALID: %s", asset_id, getattr(asset_harmonized, "rationale", ""))
        else:
            event_type = "asset.not_harmonized"
            logger.warning(
                "Asset harmonization has unknown status: %s (asset %s)",
                status_lower,
                asset_id,
            )

        return HandlerResult(
            data={"asset_id": getattr(asset_harmonized, "asset_id", None)},
            event_type=event_type,
            metadata={
                "asset_id": asset_id,
                "status": getattr(asset_harmonized, "status", None),
                "confidence": getattr(asset_harmonized, "confidence", None),
            },
        )

    def get_published_event_types(self) -> tuple[str, ...]:
        """Declare event types this handler can publish."""
        return (
            "asset.harmonized",
            "asset.not_harmonized",
            "asset.harmonization.error",
        )
