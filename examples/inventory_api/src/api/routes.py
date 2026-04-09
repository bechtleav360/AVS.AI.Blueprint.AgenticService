"""REST API routes for the Inventory API."""

from __future__ import annotations

import logging

from fastapi import HTTPException
from pydantic import BaseModel

from blueprint.agents.io.api.rest_api_base import RestApiBase

from src.models.schemas import (
    CreateProductRequest,
    Product,
    ProductSearchResult,
    UpdateProductRequest,
)
from src.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)


class StockAdjustment(BaseModel):
    """Request body for stock adjustment."""

    quantity: int


class InventoryApi(RestApiBase):
    """Product inventory CRUD endpoints."""

    def __init__(self) -> None:
        super().__init__()
        self._inventory_service: InventoryService | None = None

    async def on_startup(self) -> None:
        """Resolve the inventory service from the registry."""
        self._inventory_service = self.registry.get_service(InventoryService)  # type: ignore[assignment]
        logger.info("InventoryApi: inventory service resolved")

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    @property
    def service(self) -> InventoryService:
        """Convenience accessor that raises if called before startup."""
        if self._inventory_service is None:
            raise RuntimeError("InventoryService not resolved yet")
        return self._inventory_service

    @RestApiBase.get(
        "/products",
        response_model=list[Product],
        tags=["Products"],
        summary="List products",
    )
    async def list_products(self, category: str | None = None) -> list[Product]:
        """List all products, optionally filtered by category."""
        return self.service.list_products(category=category)

    @RestApiBase.get(
        "/products/search",
        response_model=ProductSearchResult,
        tags=["Products"],
        summary="Search products",
    )
    async def search_products(self, q: str) -> ProductSearchResult:
        """Search products by name or description."""
        return self.service.search_products(q)

    @RestApiBase.get(
        "/products/{product_id}",
        response_model=Product,
        tags=["Products"],
        summary="Get a product",
    )
    async def get_product(self, product_id: str) -> Product:
        """Get a single product by ID."""
        product = self.service.get_product(product_id)
        if product is None:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        return product

    @RestApiBase.post(
        "/products",
        response_model=Product,
        status_code=201,
        tags=["Products"],
        summary="Create a product",
    )
    async def create_product(self, request: CreateProductRequest) -> Product:
        """Create a new product."""
        return self.service.create_product(request)

    @RestApiBase.put(
        "/products/{product_id}",
        response_model=Product,
        tags=["Products"],
        summary="Update a product",
    )
    async def update_product(self, product_id: str, request: UpdateProductRequest) -> Product:
        """Update an existing product."""
        product = self.service.update_product(product_id, request)
        if product is None:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        return product

    @RestApiBase.delete(
        "/products/{product_id}",
        tags=["Products"],
        summary="Delete a product",
    )
    async def delete_product(self, product_id: str) -> dict[str, str]:
        """Delete a product by ID."""
        deleted = self.service.delete_product(product_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        return {"status": "deleted", "product_id": product_id}

    @RestApiBase.patch(
        "/products/{product_id}/stock",
        response_model=Product,
        tags=["Products"],
        summary="Adjust product stock",
    )
    async def adjust_stock(self, product_id: str, body: StockAdjustment) -> Product:
        """Adjust the stock level of a product."""
        product = self.service.update_stock(product_id, body.quantity)
        if product is None:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        return product
