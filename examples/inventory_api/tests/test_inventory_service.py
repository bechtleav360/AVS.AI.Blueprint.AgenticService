"""Unit tests for InventoryService."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.models.schemas import CreateProductRequest, UpdateProductRequest
from src.services.inventory_service import InventoryService


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create a mock cache service that behaves like a simple dict store."""
    cache = MagicMock()
    store: dict[str, Any] = {}

    def _get(key: str, namespace: str = "default") -> Any | None:
        return store.get(f"{namespace}:{key}")

    def _set(key: str, value: Any, namespace: str = "default", ttl: int | None = None) -> None:
        store[f"{namespace}:{key}"] = value

    def _delete(key: str, namespace: str = "default") -> bool:
        return store.pop(f"{namespace}:{key}", None) is not None

    cache.get = MagicMock(side_effect=_get)
    cache.set = MagicMock(side_effect=_set)
    cache.delete = MagicMock(side_effect=_delete)
    return cache


@pytest.fixture
def service(mock_cache: MagicMock) -> InventoryService:
    """Create an InventoryService with a mock cache injected."""
    svc = InventoryService.__new__(InventoryService)
    svc._products = {}
    svc._cache = mock_cache
    return svc


@pytest.fixture
def sample_request() -> CreateProductRequest:
    return CreateProductRequest(
        name="Widget",
        description="A useful widget",
        price=9.99,
        stock=100,
        category="tools",
    )


class TestCreateProduct:
    def test_create_returns_product_with_id(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        product = service.create_product(sample_request)
        assert product.id is not None
        assert product.name == "Widget"
        assert product.price == 9.99
        assert product.stock == 100
        assert product.category == "tools"
        assert product.created_at is not None

    def test_create_stores_product(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        product = service.create_product(sample_request)
        assert service.get_product(product.id) is not None


class TestGetProduct:
    def test_get_existing_product(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        product = service.create_product(sample_request)
        fetched = service.get_product(product.id)
        assert fetched is not None
        assert fetched.id == product.id

    def test_get_nonexistent_product(self, service: InventoryService) -> None:
        assert service.get_product("nonexistent-id") is None


class TestUpdateProduct:
    def test_update_existing_product(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        product = service.create_product(sample_request)
        update = UpdateProductRequest(price=19.99, name="Super Widget")
        updated = service.update_product(product.id, update)
        assert updated is not None
        assert updated.price == 19.99
        assert updated.name == "Super Widget"
        assert updated.description == "A useful widget"  # unchanged

    def test_update_nonexistent_product(self, service: InventoryService) -> None:
        update = UpdateProductRequest(price=5.0)
        assert service.update_product("nonexistent-id", update) is None


class TestDeleteProduct:
    def test_delete_existing_product(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        product = service.create_product(sample_request)
        assert service.delete_product(product.id) is True
        assert service.get_product(product.id) is None

    def test_delete_nonexistent_product(self, service: InventoryService) -> None:
        assert service.delete_product("nonexistent-id") is False


class TestSearchProducts:
    def test_search_by_name(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        service.create_product(sample_request)
        result = service.search_products("widget")
        assert result.total == 1
        assert result.products[0].name == "Widget"

    def test_search_by_description(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        service.create_product(sample_request)
        result = service.search_products("useful")
        assert result.total == 1

    def test_search_no_match(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        service.create_product(sample_request)
        result = service.search_products("nonexistent")
        assert result.total == 0
        assert result.products == []


class TestListProducts:
    def test_list_all(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        service.create_product(sample_request)
        service.create_product(
            CreateProductRequest(
                name="Gadget",
                description="A handy gadget",
                price=14.99,
                stock=50,
                category="electronics",
            )
        )
        products = service.list_products()
        assert len(products) == 2

    def test_list_filtered_by_category(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        service.create_product(sample_request)
        service.create_product(
            CreateProductRequest(
                name="Gadget",
                description="A handy gadget",
                price=14.99,
                stock=50,
                category="electronics",
            )
        )
        products = service.list_products(category="tools")
        assert len(products) == 1
        assert products[0].category == "tools"


class TestUpdateStock:
    def test_increase_stock(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        product = service.create_product(sample_request)
        updated = service.update_stock(product.id, 25)
        assert updated is not None
        assert updated.stock == 125

    def test_decrease_stock(self, service: InventoryService, sample_request: CreateProductRequest) -> None:
        product = service.create_product(sample_request)
        updated = service.update_stock(product.id, -10)
        assert updated is not None
        assert updated.stock == 90

    def test_update_stock_nonexistent(self, service: InventoryService) -> None:
        assert service.update_stock("nonexistent-id", 10) is None
