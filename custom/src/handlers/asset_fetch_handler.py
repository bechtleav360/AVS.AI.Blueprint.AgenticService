import logging
import os
from typing import Any

import httpx

from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import CustomPayload, HandlerResult

logger = logging.getLogger(__name__)


class HandlerError(Exception):
    """Domain-specific exception raised by handlers."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.code = code or "handler_error"

class AssetFetchHandler(EventHandler):
    """Fetch an asset by ID from the core index and save it to context.

    Triggers:
    event.data contains asset_id
    """

    def __init__(self) -> None:
        super().__init__("AssetFetchHandler", priority=10)

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        if not event.data:
            return False
        
        return True

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
        # Extract payload
        payload = event.data

        # Handle both CustomPayload objects and plain dictionaries
        if isinstance(payload, CustomPayload):
            asset = payload.asset
        elif isinstance(payload, dict):
            asset = payload.get("asset")
        else:
            logger.error("Invalid payload format")
            return HandlerResult(
                data={"error": "Invalid payload format"},
                event_type="invoice.analysis.error",
                metadata={"reason": "invalid_payload"},
            )
        
        context["asset"] = asset

        asset_id = asset.get("id")
        if not asset_id:
            raise HandlerResult(
                data={"error": "Invalid payload format"},
                event_type="invoice.analysis.error",
                metadata={"reason": "no asset id in payload"},
            )
        context["asset_id"] = asset_id

        base_url = os.environ.get("CORE_INDEX_URL", "https://bios-index-core-frontend-dev-bios-bechtle.apps.mgmt.env.av360.org")
        url = f"{base_url.rstrip('/')}/v1/assets/{asset_id}?referenceDepth=1"
        _api_key = ""
        _original_async_client = httpx.AsyncClient

        class _AsyncClientWithApiKey(_original_async_client):
            def __init__(self, *args, **kwargs):
                headers = kwargs.pop("headers", {}) or {}
                headers = {**headers, "X-ApiKey": _api_key}
                # disable SSL verification by default to ignore self-signed certificates
                kwargs.setdefault("verify", False)
                super().__init__(*args, headers=headers, **kwargs)

        httpx.AsyncClient = _AsyncClientWithApiKey
        
        # url = f"https://bios-index-core-frontend-dev-bios-bechtle.apps.mgmt.env.av360.org/v1/assets?pageIndex=0&pageSize=10&referenceDepth=1"
        logger.info("AssetFetchHandler fetching asset %s from %s", asset_id, url)

        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("Failed to fetch asset %s: %s", asset_id, str(exc))
                raise HandlerResult (
                    data={"error": "Asset not found"},
                    event_type="invoice.analysis.error",
                    metadata={"reason": "failed to fetch asset from index"},
                )
            except Exception as exc:
                raise HandlerResult (
                    data={"error": "Asset not found"},
                    event_type="invoice.analysis.error",
                    metadata={"reason": "failed to fetch asset from index"},
                )

        try:
            asset_json = resp.json()
        except Exception:
            asset_json = resp.text    
        logger.info("AssetFetchHandler fetched asset %s: %s", asset_id, str(asset_json))
        context["asset_fetched"] = asset_json
        logger.info("AssetFetchHandler saved asset %s into context", asset_id)
        return None
