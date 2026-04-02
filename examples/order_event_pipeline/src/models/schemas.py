"""Pydantic models for order event processing."""

from pydantic import BaseModel


class OrderItem(BaseModel):
    """A single line item in an order."""

    product_id: str
    name: str
    quantity: int
    unit_price: float


class OrderPayload(BaseModel):
    """Payload for an incoming order event."""

    order_id: str
    customer_id: str
    items: list[OrderItem]
    shipping_address: str
    total_amount: float


class OrderResult(BaseModel):
    """Result of order processing."""

    order_id: str
    status: str  # "validated" | "rejected"
    reason: str | None = None
    enriched_data: dict | None = None


class ValidationError(BaseModel):
    """A single validation error (not an exception)."""

    field: str
    message: str
