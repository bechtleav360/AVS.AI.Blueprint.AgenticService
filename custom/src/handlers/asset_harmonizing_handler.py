"""Harmonizing handler that processes fat events and harmonizes asset data.

This handler:
- Receives a fat Event with all asset data (no fetch needed)
- Invokes the harmonizing AI agent to map to canonical Asset schema
- Applies post-harmonization rules (nullify certain fields, set status, etc.)
- Returns harmonized asset ready for persistence
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from base.src.agent import PromptLoader
from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import Asset, AssetStatus, AssetType, HandlerResult, HarmonizingOutput

logger = logging.getLogger(__name__)

THIS_FILE = Path(__file__).resolve()
BLUEPRINT_ROOT = THIS_FILE.parents[1]


class AssetHarmonizingHandler(EventHandler):
    """Handler that harmonizes asset data using the AI agent.

    Expects:
    - event.data contains complete asset data (fat event)

    Returns:
    - HandlerResult with harmonized asset
    - Publishes asset.harmonized or asset.harmonizing.error events
    """

    def __init__(self) -> None:
        super().__init__("AssetHarmonizingHandler", priority=10)

    async def can_handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> bool:
        """Handle events with asset data."""
        if not event.data:
            return False

        # Check if we have source asset data
        if isinstance(event.data, dict):
            return True

        return False

    async def handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> Optional[HandlerResult]:
        """Harmonize the asset data and return structured result.

        Returns:
            HandlerResult with event_type for publishing, or None to continue chain.

        Event Types Published:
            - asset.harmonized: When harmonization succeeds
            - asset.harmonizing.error: When processing fails
        """
        logger.info(
            "AssetHarmonizingHandler processing event '%s'",
            event.type,
        )

        # Extract source data from event
        source_data = event.data
        if not source_data or not isinstance(source_data, dict):
            logger.error("Invalid or missing source data in event")
            return HandlerResult(
                data={"error": "Invalid payload format"},
                event_type="asset.harmonizing.error",
                metadata={"reason": "No source data in event"},
            )

        # Save source data to context
        context["source_asset"] = source_data

        # Normalize type if present in source data
        input_type_norm = self._normalize_type(source_data.get("type"))

        # Load optional domain context
        context_path = BLUEPRINT_ROOT / "prompts" / "asset_typen_uebersicht.md"
        try:
            context_md = context_path.read_text(encoding="utf-8")
        except Exception:
            context_md = ""
            logger.warning(
                "Could not load domain context from %s", context_path
            )

        # Build instruction prompt for the agent
        instruction = self._build_instruction(
            source_data, context_md, input_type_norm
        )

        try:
            # Get agent from registry (configured at startup)
            agent = self._get_agent("asset_harmonizing")

            # Run agent - expects Asset output
            result = await agent.run(instruction)
            
            # Parse the result - agent should return Asset schema
            harmonized_asset = Asset.model_validate_json(result.output)

            # Apply post-harmonization rules
            harmonized_asset = self._apply_post_harmonization_rules(
                harmonized_asset, input_type_norm
            )

            logger.info(
                "Asset harmonization completed: type=%s, name=%s",
                harmonized_asset.type,
                harmonized_asset.name,
            )

            # Prepare output payload with transformations
            output_payload = self._prepare_output_payload(harmonized_asset)

            # Save to context
            context["harmonized_asset"] = output_payload

            # Return success result
            return HandlerResult(
                data=output_payload,
                event_type="asset.harmonized",
                metadata={
                    "asset_type": harmonized_asset.type,
                    "asset_name": harmonized_asset.name,
                    "source_id": source_data.get("id"),
                },
            )

        except Exception as e:
            logger.error(
                "Asset harmonization failed: %s", str(e), exc_info=True
            )
            # Return error result
            return HandlerResult(
                data={"error": str(e), "source_data": source_data},
                event_type="asset.harmonizing.error",
                metadata={
                    "error_type": type(e).__name__,
                    "source": "harmonizing_processing",
                },
            )

    def get_published_event_types(self) -> tuple[str, ...]:
        """Declare event types this handler can publish.

        These event types should be mapped in values.yaml:
        - asset.harmonized -> downstream topic
        - asset.harmonizing.error -> error handling topic
        """
        return (
            "asset.harmonized",
            "asset.harmonizing.error",
        )

    def _normalize_type(self, input_type: Optional[str]) -> Optional[str]:
        """Normalize the asset type from source data.

        Args:
            input_type: Raw type string from source

        Returns:
            Normalized type (hardware/software) or None
        """
        if not input_type:
            return None
        t = str(input_type).strip().lower()
        if t == "hardware":
            return AssetType.HARDWARE
        if t == "software":
            return AssetType.SOFTWARE
        return None

    def _build_instruction(
        self,
        source_data: dict,
        context_md: str,
        input_type_norm: Optional[str],
    ) -> str:
        """Build the instruction prompt for the harmonizing agent.

        Args:
            source_data: Source asset data
            context_md: Domain context markdown
            input_type_norm: Normalized type hint

        Returns:
            Formatted instruction string
        """
        instructions = (
            "You are an expert in asset data harmonization.\n"
            "Map the provided input JSON to the canonical Asset schema.\n"
            "Strict rules (must follow):\n"
            "- Only accept assets of type 'hardware' or 'software'. Do not output other types. If unsure, leave type null.\n"
            "- The following fields MUST be null in the output (per after-harmonizing spec): id, externalId, tags, references.\n"
            "- The field 'status' MUST be set to 'draft'.\n"
            "- Use only the schema fields defined by the model (no extras).\n"
            "- Do not hallucinate values. If data is missing, leave fields null.\n"
            "- If input indicates 'Hardware', set Asset.type='hardware' and populate the 'hardware' extension; leave 'software' null.\n"
            "- If input indicates 'Software', set Asset.type='software' and populate the 'software' extension; leave 'hardware' null.\n"
            "- Populate meaningful 'name' and a concise, informative 'description' derived from the input (no marketing fluff).\n"
            "- Extract and map extension fields precisely: for hardware (manufacturer, model); for software (manufacturer, version, licenseType).\n"
            "- For now, do NOT use 'additionalProperties'. If something is unmapped, omit it.\n"
            "- Output ONLY a pure JSON object compatible with the schema. No prose, no Markdown, no code fences/backticks, no <think> tags."
        )

        parts = []
        if context_md:
            parts.append("Context (asset types):\n\n" + context_md)

        parts.append(
            "Input JSON:\n" + json.dumps(source_data, ensure_ascii=False, indent=2)
        )

        if input_type_norm:
            parts.append(f"\nNormalized type hint: {input_type_norm}")

        user_msg = "\n\n".join(parts)
        return f"{instructions}\n\n{user_msg}"

    def _apply_post_harmonization_rules(
        self, asset: Asset, input_type_norm: Optional[str]
    ) -> Asset:
        """Apply post-harmonization rules to ensure compliance.

        Args:
            asset: Harmonized asset from agent
            input_type_norm: Normalized type hint from source

        Returns:
            Asset with enforced rules
        """
        # Enforce extension consistency with normalized type
        if input_type_norm == AssetType.HARDWARE:
            asset.type = AssetType.HARDWARE
            asset.software = None
        elif input_type_norm == AssetType.SOFTWARE:
            asset.type = AssetType.SOFTWARE
            asset.hardware = None

        # Only hardware/software types are permitted
        if asset.type not in (AssetType.HARDWARE, AssetType.SOFTWARE):
            asset.type = None

        # Status must always be draft
        asset.status = AssetStatus.DRAFT

        # Fields that must be null after harmonizing
        asset.id = None
        asset.externalId = None
        asset.tags = None
        asset.references = None

        return asset

    def _prepare_output_payload(self, asset: Asset) -> dict:
        """Prepare the output payload with custom transformations.

        Args:
            asset: Harmonized asset

        Returns:
            Output dictionary ready for serialization
        """
        output_payload = asset.model_dump()

        # Drop additionalProperties from output (even if present)
        output_payload.pop("additionalProperties", None)

        # Extension handling: omit null extension and rename the present one
        hw = output_payload.pop("hardware", None)
        sw = output_payload.pop("software", None)
        if hw is not None:
            output_payload["hardware_extension"] = hw
        if sw is not None:
            output_payload["software_extension"] = sw

        return output_payload
