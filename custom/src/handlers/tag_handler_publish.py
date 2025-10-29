import logging
from typing import Any


from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import HandlerResult, AssetTaggingOutput

logger = logging.getLogger(__name__)


class HandlerError(Exception):
    """Domain-specific exception raised by handlers."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.code = code or "handler_error"


class AssetTaggedEventPublish(EventHandler):
    """Post evaluated tags to the core index for the asset.

    Triggers:
    - context contains tags and asset

    Returns:
        HandlerResult with event_type for publishing, or None to continue chain.

    Event Types Published:
        - asset.tagged: When asset status is 'tagged'
        - asset.not_tagged: When asset tagging status is 'invalid' or 'incomplete'
        - asset.analysis.error: When processing fails
    """

    def __init__(self) -> None:
        super().__init__("AssetTaggedEventPublish", priority=40)

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        if not event.data:
            return False
        return bool(context.get("asset_tagged")) and bool(context.get("asset_fetched"))

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
        asset = context.get("asset_fetched")
        if not asset or not isinstance(asset, dict):
            raise HandlerError(status="invalid", reason="No asset in context to update tags")

        asset_id = asset.get("id")
        if not asset_id:
            raise HandlerError(status="invalid", reason="Asset ID missing for tag update")

        asset_tagged: AssetTaggingOutput = context.get("asset_tagged")
        tags = asset_tagged.category.name
        if not tags:
            raise HandlerError(status="invalid", reason="No tags available to submit")

        # Determine which event to publish based on validation status
        if asset_tagged.status.lower() == "valid":
            event_type = "asset.tagged"
            logger.info("Asset %s is tagged sucessfully", asset_id)
        elif asset_tagged.status.lower() in ["invalid", "incomplete"]:
            event_type = "asset.not_tagged"
            logger.warning(
                "Invoice %s is INVALID: %s", asset_id, asset_tagged.rationale
            )
        else:
            # Unknown status - treat as invalid
            event_type = "asset.not_tagged"
            logger.warning(
                "Asset tagging %s has unknown status: %s",
                asset_tagged.status,
                asset_id,
            )

        # Return structured result with event type for publishing
        return HandlerResult(
            data={"asset_id": asset_tagged.asset_id},
            event_type=event_type,
            metadata={
                "asset_id": asset_id,
                "status": asset_tagged.status,
                "confidence": asset_tagged.confidence,
            },
        )

    def get_published_event_types(self) -> tuple[str, ...]:
        """Declare event types this handler can publish.

        These event types are mapped in values.yaml:
        - asset.tagged -> test.connection (routing_key: valid)
        - asset.not_tagged -> test.connection (routing_key: invalid)
        - asset.analysis.error -> test.connection (routing_key: error)
        """
        return (
            "asset.tagged",
            "asset.not_tagged",
            "asset.analysis.error",
        )
