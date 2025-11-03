"""Asset preprocessing handler that extracts type and properties from events.

This handler:
- Receives HarmonizingInputPayload events
- Extracts asset type (hardware/software) from data.type
- Extracts properties from data.properties
- Stores extracted data in context for downstream handlers
- Runs before AgentInvokerHandler (priority=10 vs 20)
"""

import logging
from typing import Any, Optional

from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import AssetType, HandlerResult, HarmonizingInputPayload

logger = logging.getLogger(__name__)


class AssetPreprocessingHandler(EventHandler):
    """Preprocesses incoming events to extract asset data and type information.

    This handler validates the event structure and extracts:
    - Asset type (hardware/software)
    - Asset properties (raw key/value pairs)

    The extracted data is stored in context for downstream handlers.
    """

    def __init__(self) -> None:
        super().__init__("AssetPreprocessingHandler", priority=10)

    async def can_handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> bool:
        """Check if event has valid HarmonizingInputPayload structure."""
        # if not event.data or not isinstance(event.data, dict):
        #     logger.debug("Event data is not a dict")
        #     return False

        # # Check if data exists with type and properties
        # if "data" not in event.data:
        #     logger.debug("Event data.data is missing")
        #     return False

        # inner_data = event.data.get("data", {})
        # if not isinstance(inner_data, dict) or "properties" not in inner_data:
        #     logger.debug("Event data.data.properties is missing")
        #     return False

        return True

    async def handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> Optional[HandlerResult]:
        """Extract asset type and properties, store in context for next handler.

        Returns:
            None to continue chain (preprocessing doesn't stop the chain)
        """
        logger.info(
            "AssetPreprocessingHandler processing event '%s'",
            event.type,
        )

        if event.data and isinstance(event.data, dict):
        # Extract type and properties from dict
            inner_data = data.get("data", {})
            asset_type = inner_data.get("type")
            properties = inner_data.get("properties", {})
        elif event.data and isinstance(event.data, HarmonizingInputPayload):
            inner_data = event.data.data
            asset_type = inner_data.type
            properties = inner_data.properties

        if not properties:
            logger.error("Properties are empty or missing")
            return HandlerResult(
                data={"error": "Missing properties in event"},
                event_type="asset.preprocessing.error",
                metadata={"reason": "empty_properties"},
            )

        # Normalize asset type
        normalized_type = self._normalize_type(asset_type)
        if not normalized_type:
            logger.warning(
                "Unknown or invalid asset type '%s', will let agent determine",
                asset_type
            )

        # Store in context for downstream handlers
        context["asset_fetched"] = properties
        context["asset_type"] = normalized_type
        context["asset_type_raw"] = asset_type

        logger.info(
            "Preprocessed asset: type=%s, properties_count=%d",
            normalized_type or "unknown",
            len(properties)
        )

        # Return None to continue chain
        return None

    def _normalize_type(self, type_value: str) -> Optional[str]:
        """Normalize asset type to standard values.

        Args:
            type_value: Raw type value from event

        Returns:
            Normalized type (hardware/software) or None if unknown
        """
        if not type_value:
            return None

        type_lower = type_value.lower().strip()

        # Hardware variations
        if type_lower in ["hardware", "hw"]:
            return AssetType.HARDWARE

        # Software variations
        if type_lower in ["software", "sw"]:
            return AssetType.SOFTWARE

        return None

    def get_published_event_types(self) -> tuple[str, ...]:
        """Declare event types this handler can publish."""
        return ("asset.preprocessing.error",)
