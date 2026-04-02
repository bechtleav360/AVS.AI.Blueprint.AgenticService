"""Business logic for order validation and enrichment."""

import logging
from datetime import UTC, datetime

from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.services.infrastructure.cache_service import CacheService

from ..models.schemas import OrderPayload, ValidationError

logger = logging.getLogger(__name__)


class OrderService(ServiceBase):
    """Service that validates and enriches order payloads."""

    def __init__(self) -> None:
        super().__init__()
        self._cache: CacheService | None = None

    async def on_startup(self) -> None:
        """Acquire a reference to the cache service on startup."""
        self._cache = self.registry.cache_service
        logger.info("OrderService started with cache service")

    async def on_shutdown(self) -> None:
        """No-op shutdown."""

    def validate_order(
        self, payload: OrderPayload
    ) -> tuple[bool, list[ValidationError]]:
        """Validate an order payload.

        Checks:
        - items list is not empty
        - total_amount is greater than zero
        - shipping_address is not empty

        Returns:
            Tuple of (is_valid, list_of_errors).
        """
        errors: list[ValidationError] = []

        if not payload.items:
            errors.append(
                ValidationError(field="items", message="Order must contain at least one item")
            )

        if payload.total_amount <= 0:
            errors.append(
                ValidationError(field="total_amount", message="Total amount must be greater than zero")
            )

        if not payload.shipping_address or not payload.shipping_address.strip():
            errors.append(
                ValidationError(field="shipping_address", message="Shipping address is required")
            )

        is_valid = len(errors) == 0
        return is_valid, errors

    def enrich_order(self, payload: OrderPayload) -> dict:
        """Enrich a validated order with computed fields.

        Adds:
        - tax_amount: 10% of total_amount
        - shipping_estimate: simple heuristic based on item count
        - processed_at: current UTC timestamp

        Returns:
            Dict containing the original order data plus enrichment fields.
        """
        tax_amount = round(payload.total_amount * 0.10, 2)
        item_count = sum(item.quantity for item in payload.items)
        shipping_estimate = "3-5 business days" if item_count <= 5 else "5-7 business days"

        return {
            "order_id": payload.order_id,
            "customer_id": payload.customer_id,
            "items": [item.model_dump() for item in payload.items],
            "shipping_address": payload.shipping_address,
            "total_amount": payload.total_amount,
            "tax_amount": tax_amount,
            "grand_total": round(payload.total_amount + tax_amount, 2),
            "shipping_estimate": shipping_estimate,
            "processed_at": datetime.now(UTC).isoformat(),
        }

    def cache_order_status(self, order_id: str, status: str, data: dict) -> None:
        """Persist order status in the cache."""
        if self._cache is not None:
            self._cache.set(
                order_id,
                {"order_id": order_id, "status": status, **data},
                namespace="orders",
            )

    def get_cached_order(self, order_id: str) -> dict | None:
        """Retrieve a cached order by ID."""
        if self._cache is not None:
            return self._cache.get(order_id, namespace="orders")
        return None
