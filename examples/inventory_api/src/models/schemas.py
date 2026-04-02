"""Pydantic models for the Inventory API."""

from __future__ import annotations

from datetime import datetime, timezone
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateProductRequest(BaseModel):
    """Request body for creating a new product."""

    name: str
    description: str
    price: float
    stock: int
    category: str


class UpdateProductRequest(BaseModel):
    """Request body for updating an existing product. All fields are optional."""

    name: str | None = None
    description: str | None = None
    price: float | None = None
    stock: int | None = None
    category: str | None = None


class ProductSearchResult(BaseModel):
    """Response for product search queries."""

    products: list[Product]
    total: int
