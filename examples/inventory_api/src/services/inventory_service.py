"""Inventory business service with in-memory product storage and caching."""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from uuid import uuid4

from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.services.infrastructure.cache_service import CacheService

from src.models.schemas import (
    CreateProductRequest,
    Product,
    ProductSearchResult,
    UpdateProductRequest,
)

logger = logging.getLogger(__name__)

CACHE_NAMESPACE = "products"


class InventoryService(ServiceBase):
    """Manages product inventory with in-memory storage and optional caching."""

    def __init__(self) -> None:
        super().__init__()
        self._products: dict[str, Product] = {}
        self._cache: CacheService | None = None

    async def on_startup(self) -> None:
        """Resolve the cache service from the registry."""
        if self.registry.has_cache():
            self._cache = self.registry.cache_service
            logger.info("InventoryService: cache service attached")
        else:
            logger.info("InventoryService: running without cache")

    async def on_shutdown(self) -> None:
        """Clean up resources."""
        logger.info("InventoryService shutting down with %d products", len(self._products))

    def list_products(self, category: str | None = None) -> list[Product]:
        """Return all products, optionally filtered by category."""
        products = list(self._products.values())
        if category:
            products = [p for p in products if p.category.lower() == category.lower()]
        return products

    def get_product(self, product_id: str) -> Product | None:
        """Retrieve a single product by ID, checking cache first."""
        if self._cache:
            cached = self._cache.get(product_id, namespace=CACHE_NAMESPACE)
            if cached is not None:
                logger.debug("Cache hit for product %s", product_id)
                return Product.model_validate(cached)

        product = self._products.get(product_id)
        if product and self._cache:
            self._cache.set(
                product_id,
                product.model_dump(mode="json"),
                namespace=CACHE_NAMESPACE,
            )
        return product

    def create_product(self, request: CreateProductRequest) -> Product:
        """Create a new product with a generated UUID and timestamp."""
        product = Product(
            id=str(uuid4()),
            name=request.name,
            description=request.description,
            price=request.price,
            stock=request.stock,
            category=request.category,
            created_at=datetime.now(UTC),
        )
        self._products[product.id] = product

        if self._cache:
            self._cache.set(
                product.id,
                product.model_dump(mode="json"),
                namespace=CACHE_NAMESPACE,
            )

        logger.info("Created product %s (%s)", product.id, product.name)
        return product

    def update_product(self, product_id: str, request: UpdateProductRequest) -> Product | None:
        """Update an existing product. Returns None if not found."""
        product = self._products.get(product_id)
        if product is None:
            return None

        update_data = request.model_dump(exclude_unset=True)
        updated = product.model_copy(update=update_data)
        self._products[product_id] = updated

        if self._cache:
            self._cache.set(
                product_id,
                updated.model_dump(mode="json"),
                namespace=CACHE_NAMESPACE,
            )

        logger.info("Updated product %s", product_id)
        return updated

    def delete_product(self, product_id: str) -> bool:
        """Delete a product by ID. Returns True if it existed."""
        if product_id not in self._products:
            return False

        del self._products[product_id]

        if self._cache:
            self._cache.delete(product_id, namespace=CACHE_NAMESPACE)

        logger.info("Deleted product %s", product_id)
        return True

    def search_products(self, query: str) -> ProductSearchResult:
        """Search products by name or description (case-insensitive)."""
        q = query.lower()
        matches = [p for p in self._products.values() if q in p.name.lower() or q in p.description.lower()]
        return ProductSearchResult(products=matches, total=len(matches))

    def update_stock(self, product_id: str, quantity: int) -> Product | None:
        """Adjust the stock level of a product by the given quantity.

        Args:
            product_id: The product to update.
            quantity: The amount to add (positive) or subtract (negative).

        Returns:
            The updated product, or None if not found.
        """
        product = self._products.get(product_id)
        if product is None:
            return None

        updated = product.model_copy(update={"stock": product.stock + quantity})
        self._products[product_id] = updated

        if self._cache:
            self._cache.set(
                product_id,
                updated.model_dump(mode="json"),
                namespace=CACHE_NAMESPACE,
            )

        logger.info(
            "Stock updated for product %s: %d -> %d",
            product_id,
            product.stock,
            updated.stock,
        )
        return updated
