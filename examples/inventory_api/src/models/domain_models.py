"""Domain models: what InventoryService works with. No request DTO reaches the service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class Product(BaseModel):
    """A product in the inventory."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    price: float
    stock: int
    category: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NewProduct(BaseModel):
    """A product to create: everything but the id and the timestamp, which the service assigns."""

    name: str
    description: str
    price: float
    stock: int
    category: str


class ProductChanges(BaseModel):
    """The fields to change on a product; only the fields that are set are applied."""

    name: str | None = None
    description: str | None = None
    price: float | None = None
    stock: int | None = None
    category: str | None = None
