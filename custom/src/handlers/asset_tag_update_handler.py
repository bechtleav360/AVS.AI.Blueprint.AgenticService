import logging
import os
from typing import Any

import httpx

from base.src.handler import EventHandler
from base.src.models import CloudEvent

from ..models import AssetTaggingOutput

logger = logging.getLogger(__name__)


class HandlerError(Exception):
    """Domain-specific exception raised by handlers."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.code = code or "handler_error"


class AssetTagUpdateHandler(EventHandler):
    """Post evaluated tags to the core index for the asset.

    Triggers:
    - context contains tags and asset
    """

    def __init__(self) -> None:
        super().__init__("AssetTagUpdateHandler", priority=30)

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

        if not isinstance(tags, (list, tuple)):
            tags = [str(tags)]
        logger.info(tags)
        base_url = os.environ.get("CORE_INDEX_URL", "https://bios-index-core-frontend-dev-bios-bechtle.apps.mgmt.env.av360.org")
        url = f"{base_url.rstrip('/')}/v1/assets/{asset_id}/tags"
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

        logger.info("AssetTagUpdateHandler submitting %d tags for asset %s", len(tags), asset_id)

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.patch(url, json=tags)
                resp.raise_for_status()
            except Exception as exc:
                logger.error("Failed to submit tags for asset %s: %s", asset_id, str(exc))
                raise HandlerError(status="error", reason="Failed to submit tags to asset service")

        try:
            result = resp.json()
        except Exception:
            result = resp.text

        logger.debug("AssetTagUpdateHandler updated tags for %s", asset_id)
        return None
