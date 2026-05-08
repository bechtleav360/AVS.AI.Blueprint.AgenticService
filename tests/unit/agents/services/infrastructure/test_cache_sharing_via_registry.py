"""Two services sharing the same cache through Component.shared_registry.

This is the practical case a user encounters when they do:

    AppBuilder(config)
        .with_service(ServiceA)
        .with_service(ServiceB)
        .with_cache()
        .build()

Both ServiceA and ServiceB pull `self.registry.cache_service` in `on_startup()`.
The contract is: they get the SAME cache instance, so anything one writes
the other can read.

These tests use a real (non-mocked) DiskCacheService backed by a tmp dir, plus
a real Registry. No external services required.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.services.infrastructure.cache_service import DiskCacheService
from blueprint.agents.services.service_base import ServiceBase

NAMESPACE = "shared"


# ---------------------------------------------------------------------------
# Two minimal services that pull the cache from the registry on startup
# ---------------------------------------------------------------------------


class WriterService(ServiceBase):
    """Writes a value to the shared cache."""

    async def on_startup(self) -> None:
        self._cache = self.registry.cache_service

    async def on_shutdown(self) -> None:
        return None

    def write(self, key: str, value: dict) -> None:
        self._cache.set(key, value, namespace=NAMESPACE)

    def read(self, key: str) -> dict | None:
        return self._cache.get(key, namespace=NAMESPACE)


class ReaderService(ServiceBase):
    """Reads values from the shared cache."""

    async def on_startup(self) -> None:
        self._cache = self.registry.cache_service

    async def on_shutdown(self) -> None:
        return None

    def write(self, key: str, value: dict) -> None:
        self._cache.set(key, value, namespace=NAMESPACE)

    def read(self, key: str) -> dict | None:
        return self._cache.get(key, namespace=NAMESPACE)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    """Reset Component class-level state between tests so each test starts fresh."""
    yield
    Component.shared_config = None
    Component.shared_registry = None


@pytest.fixture
def shared_cache(tmp_path: Path) -> Generator[DiskCacheService]:
    """A real DiskCacheService backed by a per-test tmp dir."""
    cache = DiskCacheService(cache_dir=str(tmp_path / "shared"), enable_locking=False)
    yield cache
    cache.close()


@pytest.fixture
def two_services_sharing_cache(
    shared_cache: DiskCacheService,
) -> Generator[tuple[WriterService, ReaderService]]:
    """Build a real Registry, register both services and the shared cache,
    and run on_startup so each service resolves cache_service from the registry."""
    Component.shared_registry = Registry(Component)

    writer = WriterService()
    reader = ReaderService()
    Component.shared_registry.cache_service = shared_cache

    import asyncio

    asyncio.run(writer.on_startup())
    asyncio.run(reader.on_startup())

    yield writer, reader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTwoServicesShareCacheViaRegistry:
    def test_both_services_resolve_the_same_cache_instance(
        self, two_services_sharing_cache: tuple[WriterService, ReaderService]
    ) -> None:
        writer, reader = two_services_sharing_cache
        assert writer._cache is reader._cache, (
            "Both services should pull the SAME cache instance from the registry"
        )

    def test_reader_sees_writers_write(
        self, two_services_sharing_cache: tuple[WriterService, ReaderService]
    ) -> None:
        writer, reader = two_services_sharing_cache
        writer.write("user:42", {"name": "Alice"})

        assert reader.read("user:42") == {"name": "Alice"}

    def test_writer_sees_readers_write(
        self, two_services_sharing_cache: tuple[WriterService, ReaderService]
    ) -> None:
        writer, reader = two_services_sharing_cache
        reader.write("session:xyz", {"token": "abc-123"})

        assert writer.read("session:xyz") == {"token": "abc-123"}

    def test_bidirectional_write_read_round_trip(
        self, two_services_sharing_cache: tuple[WriterService, ReaderService]
    ) -> None:
        """The full practical case: each service writes, the other reads.

        Mirrors what cache-consumer-demo's PricingService and RecommendationService do
        in the README walkthrough.
        """
        writer, reader = two_services_sharing_cache

        writer.write("price:laptop", {"amount": 49.99})
        reader.write("recommendation:laptop", {"verdict": "BUY"})

        # Each service reads what the other wrote
        assert reader.read("price:laptop") == {"amount": 49.99}
        assert writer.read("recommendation:laptop") == {"verdict": "BUY"}

        # And each service still sees its own write
        assert writer.read("price:laptop") == {"amount": 49.99}
        assert reader.read("recommendation:laptop") == {"verdict": "BUY"}

    def test_registry_setter_rejects_double_registration(
        self, shared_cache: DiskCacheService, tmp_path: Path
    ) -> None:
        """AC-protection: assigning a 2nd cache to the registry raises, ensuring
        a single source of truth across all services."""
        Component.shared_registry = Registry(Component)
        Component.shared_registry.cache_service = shared_cache

        second_cache = DiskCacheService(cache_dir=str(tmp_path / "second"), enable_locking=False)
        try:
            with pytest.raises(ValueError):
                Component.shared_registry.cache_service = second_cache
        finally:
            second_cache.close()
