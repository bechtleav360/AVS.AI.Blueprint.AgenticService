"""Domain models: what OrderService works with. No CloudEvent and no DTO reaches the service."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class OrderLine(BaseModel):
    """One line of an order."""

    product_id: str
    name: str
    quantity: int
    unit_price: float


class Order(BaseModel):
    """An order to process."""

    order_id: str
    customer_id: str
    items: list[OrderLine]
    shipping_address: str
    total_amount: float


class ValidationError(BaseModel):
    """A single validation error (not an exception)."""

    field: str
    message: str


class OrderOutcome(BaseModel):
    """What OrderService decided: ``rejected`` with the errors, or ``validated`` with the enriched order."""

    status: Literal["validated", "rejected"]
    data: dict[str, Any] = Field(default_factory=dict)
