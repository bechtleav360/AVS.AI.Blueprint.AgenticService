"""DTOs: the REST API's wire contract."""

from __future__ import annotations

from pydantic import BaseModel

from .domain_models import Product


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


class StockAdjustment(BaseModel):
    """Request body for stock adjustment."""

    quantity: int


class ProductSearchResult(BaseModel):
    """Response for product search queries."""

    products: list[Product]
    total: int
