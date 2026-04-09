"""REST API routes for querying order status."""

import logging
from typing import Any

from fastapi import HTTPException

from blueprint.agents.io.api.rest_api_base import RestApiBase

from src.services.order_service import OrderService

logger = logging.getLogger(__name__)


class OrderApi(RestApiBase):
    """Exposes cached order data via REST endpoints."""

    def __init__(self) -> None:
        super().__init__()
        self._order_service: OrderService | None = None

    async def on_startup(self) -> None:
        self._order_service = self.registry.get_service(OrderService)  # type: ignore[assignment]
        logger.info("OrderApi started")

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get(
        "/orders/{order_id}",
        summary="Get order status by ID",
        tags=["Orders"],
    )
    async def get_order(self, order_id: str) -> dict[str, Any]:
        """Return the cached status and data for a single order."""
        assert self._order_service is not None
        result = self._order_service.get_cached_order(order_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        return result

    @RestApiBase.get(
        "/orders",
        summary="List recent processed orders",
        tags=["Orders"],
    )
    async def list_orders(self) -> dict[str, Any]:
        """Return a summary of recently processed orders from the cache.

        Because DiskCache does not natively support listing by namespace,
        this endpoint returns a status message. Individual orders should be
        queried by ID.
        """
        return {
            "message": "Use GET /api/orders/{order_id} to retrieve a specific order.",
            "hint": "Order IDs are returned in event payloads after processing.",
        }
