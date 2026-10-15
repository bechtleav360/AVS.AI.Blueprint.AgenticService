"""DTOs: the payload of an ``order.created`` event."""

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
