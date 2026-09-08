"""Unit tests for AgentScopedCache -- one cache, isolated per agent (spec sec. 8)."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.services.infrastructure.agent_scoped_cache import AgentScopedCache
from blueprint.agents.services.infrastructure.cache_service import DiskCacheService


@pytest.fixture
def backend(tmp_path: Path) -> Iterator[DiskCacheService]:
    """A real disk cache, because what is under test is which keys end up where."""
    cache = DiskCacheService(cache_dir=str(tmp_path / "cache"), enable_locking=False)
    yield cache
    cache.close()


@pytest.fixture
def orders(backend: DiskCacheService) -> AgentScopedCache:
    return AgentScopedCache(backend, "orders")


@pytest.fixture
def billing(backend: DiskCacheService) -> AgentScopedCache:
    return AgentScopedCache(backend, "billing")


class TestIsolation:
    def test_two_agents_do_not_see_each_others_values(self, orders: AgentScopedCache, billing: AgentScopedCache) -> None:
        """The whole point: the same key in the same partition name, kept apart."""
        orders.set("laptop", {"price": 1}, namespace="prices")
        billing.set("laptop", {"price": 2}, namespace="prices")

        assert orders.get("laptop", namespace="prices") == {"price": 1}
        assert billing.get("laptop", namespace="prices") == {"price": 2}

    def test_a_neighbours_key_reads_as_absent(self, orders: AgentScopedCache, billing: AgentScopedCache) -> None:
        billing.set("laptop", {"price": 2}, namespace="prices")
        assert orders.get("laptop", namespace="prices") is None
        assert orders.exists("laptop", namespace="prices") is False

    def test_one_backend_serves_every_agent(self, orders: AgentScopedCache, billing: AgentScopedCache, backend: DiskCacheService) -> None:
        """No second directory and no second connection -- that is why the keys carry the agent."""
        assert orders.backend is billing.backend is backend

    def test_the_partition_carries_the_agent(self, orders: AgentScopedCache, billing: AgentScopedCache, backend: DiskCacheService) -> None:
        orders.set("laptop", 1, namespace="prices")
        billing.set("laptop", 2, namespace="prices")
        assert backend.list_namespaces() == ["billing.prices", "orders.prices"]

    def test_an_agent_lists_its_partitions_by_the_names_it_used(self, orders: AgentScopedCache, billing: AgentScopedCache) -> None:
        orders.set("laptop", 1, namespace="prices")
        orders.set("session", 1, namespace="sessions")
        billing.set("laptop", 2, namespace="prices")

        assert orders.list_namespaces() == ["prices", "sessions"]

    def test_the_default_partition_is_scoped_too(self, orders: AgentScopedCache, billing: AgentScopedCache) -> None:
        orders.set("k", 1)
        billing.set("k", 2)
        assert (orders.get("k"), billing.get("k")) == (1, 2)

    def test_delete_only_reaches_this_agent(self, orders: AgentScopedCache, billing: AgentScopedCache) -> None:
        orders.set("laptop", 1, namespace="prices")
        billing.set("laptop", 2, namespace="prices")

        orders.delete("laptop", namespace="prices")

        assert orders.get("laptop", namespace="prices") is None
        assert billing.get("laptop", namespace="prices") == 2

    def test_claim_is_per_agent(self, orders: AgentScopedCache, billing: AgentScopedCache) -> None:
        """Two agents' schedulers must not steal each other's tick slots."""
        assert orders.claim("tick", "held", namespace="ticks", ttl=60) is True
        assert billing.claim("tick", "held", namespace="ticks", ttl=60) is True
        assert orders.claim("tick", "held", namespace="ticks", ttl=60) is False


class TestClear:
    def test_clearing_one_partition_leaves_the_neighbour(self, orders: AgentScopedCache, billing: AgentScopedCache) -> None:
        orders.set("laptop", 1, namespace="prices")
        billing.set("laptop", 2, namespace="prices")

        orders.clear("prices")

        assert orders.get("laptop", namespace="prices") is None
        assert billing.get("laptop", namespace="prices") == 2

    def test_clearing_everything_means_everything_of_this_agent(self, orders: AgentScopedCache, billing: AgentScopedCache) -> None:
        """The backend's own clear(None) would take the neighbours with it."""
        orders.set("a", 1, namespace="prices")
        orders.set("b", 1, namespace="sessions")
        billing.set("c", 2, namespace="prices")

        orders.clear()

        assert orders.list_namespaces() == []
        assert billing.get("c", namespace="prices") == 2


class TestOwnership:
    def test_closing_the_shared_backend_is_refused(self, orders: AgentScopedCache, backend: DiskCacheService) -> None:
        with pytest.raises(RuntimeError, match="shared with every other agent"):
            orders.close()

    def test_the_root_namespace_cannot_be_wrapped(self, backend: DiskCacheService) -> None:
        """The root reads the backend directly; wrapping it would move an existing app's keys."""
        with pytest.raises(ValueError, match="needs an agent namespace"):
            AgentScopedCache(backend, "")

    def test_it_does_not_register_itself(self, backend: DiskCacheService) -> None:
        """One lens per agent per cache would otherwise add a registry entry each."""
        Component.reset_shared_state()
        registry = Registry(Component)
        Component.shared_registry = registry

        AgentScopedCache(backend, "orders")

        assert registry.get_component_names_by_type(AgentScopedCache) == []

    def test_stats_come_from_the_backend_and_name_the_agent(self, orders: AgentScopedCache) -> None:
        """Size and eviction belong to the one shared store; there is nothing per-agent to report."""
        assert orders.get_stats()["agent"] == "orders"

    def test_hash_is_the_backends(self, orders: AgentScopedCache, backend: DiskCacheService) -> None:
        assert orders.hash("laptop") == backend.hash("laptop")


class TestThroughTheRegistry:
    """How a component actually gets one: it asks for a cache and is handed its own view."""

    @pytest.fixture
    def registry(self, backend: DiskCacheService) -> Registry:
        Component.reset_shared_state()
        registry = Registry(Component)
        Component.shared_registry = registry
        registry.add_cache("default", backend)
        return registry

    def test_a_namespaced_view_gets_a_scoped_cache(self, registry: Registry) -> None:
        cache = registry.for_namespace("orders").cache_service
        assert isinstance(cache, AgentScopedCache)
        assert cache.agent == "orders"

    def test_the_root_gets_the_backend_itself(self, registry: Registry, backend: DiskCacheService) -> None:
        """Unchanged for every single-agent application, and the opt-in for a shared cache."""
        assert registry.cache_service is backend

    def test_asking_twice_gives_one_lens(self, registry: Registry) -> None:
        view = registry.for_namespace("orders")
        assert view.cache_service is view.cache_service

    def test_two_agents_get_different_lenses(self, registry: Registry) -> None:
        orders = registry.for_namespace("orders").cache_service
        billing = registry.for_namespace("billing").cache_service
        assert orders is not billing

    def test_a_named_cache_is_scoped_too(self, registry: Registry, backend: DiskCacheService) -> None:
        registry.add_cache("sessions", backend)
        cache = registry.for_namespace("orders").get_cache("sessions")
        assert isinstance(cache, AgentScopedCache)

    def test_an_unregistered_name_still_raises_on_a_view(self, registry: Registry) -> None:
        with pytest.raises(ValueError, match="No cache registered as 'prompts'"):
            registry.for_namespace("orders").get_cache("prompts")
