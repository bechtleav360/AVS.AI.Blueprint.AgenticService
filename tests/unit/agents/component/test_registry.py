"""Unit tests for the component Registry."""

import logging

import pytest
from unittest.mock import MagicMock

from blueprint.agents.component.registry import Registry


class StubBase:
    """Root type used as component_class for the registry under test."""


class StubA(StubBase):
    pass


class StubB(StubBase):
    pass


@pytest.fixture
def registry() -> Registry:
    return Registry(StubBase)


class TestInit:
    def test_rejects_non_class(self) -> None:
        with pytest.raises(ValueError):
            Registry("not_a_class")

    def test_accepts_valid_class(self) -> None:
        assert Registry(StubBase) is not None


class TestAddComponent:
    def test_happy_path(self, registry: Registry) -> None:
        comp = StubA()
        registry.add_component("a", comp)
        assert registry.has_component("a")

    def test_rejects_wrong_type(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.add_component("bad", object())

    def test_rejects_duplicate_name(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        with pytest.raises(ValueError):
            registry.add_component("a", StubA())


class TestGetComponent:
    def test_by_name_returns_component(self, registry: Registry) -> None:
        comp = StubA()
        registry.add_component("a", comp)
        assert registry.get_component("a") is comp

    def test_by_name_not_found_raises(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.get_component("missing")

    def test_by_class_single_match(self, registry: Registry) -> None:
        comp = StubA()
        registry.add_component("a", comp)
        assert registry.get_component(StubA) is comp

    def test_by_class_no_match_raises(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.get_component(StubA)

    def test_by_class_multiple_matches_raises(self, registry: Registry) -> None:
        registry.add_component("a1", StubA())
        registry.add_component("a2", StubA())
        with pytest.raises(ValueError):
            registry.get_component(StubA)


class TestGetComponentsByType:
    def test_returns_matching_subset(self, registry: Registry) -> None:
        a, b = StubA(), StubB()
        registry.add_component("a", a)
        registry.add_component("b", b)
        assert registry.get_components_by_type(StubA) == [a]

    def test_returns_empty_when_none(self, registry: Registry) -> None:
        assert registry.get_components_by_type(StubA) == []

    def test_returns_all_matching(self, registry: Registry) -> None:
        a1, a2 = StubA(), StubA()
        registry.add_component("a1", a1)
        registry.add_component("a2", a2)
        result = registry.get_components_by_type(StubA)
        assert len(result) == 2
        assert a1 in result and a2 in result


class TestGetComponentNamesByType:
    def test_returns_matching_names(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        registry.add_component("b", StubB())
        assert registry.get_component_names_by_type(StubA) == ["a"]

    def test_returns_empty_when_none(self, registry: Registry) -> None:
        assert registry.get_component_names_by_type(StubA) == []


class TestUpdateComponentName:
    def test_renames_component(self, registry: Registry) -> None:
        comp = StubA()
        registry.add_component("old", comp)
        registry.update_component_name("old", "new")
        assert registry.has_component("new")
        assert not registry.has_component("old")
        assert registry.get_component("new") is comp

    def test_raises_on_unknown_old_name(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.update_component_name("nonexistent", "new")


class TestHasComponent:
    def test_by_name_true(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        assert registry.has_component("a") is True

    def test_by_name_false(self, registry: Registry) -> None:
        assert registry.has_component("missing") is False

    def test_by_class_true(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        assert registry.has_component(StubA) is True

    def test_by_class_false(self, registry: Registry) -> None:
        assert registry.has_component(StubA) is False


class TestHasComponentOfType:
    def test_type_only_true(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        assert registry.has_component_of_type(StubA) is True

    def test_type_only_false(self, registry: Registry) -> None:
        assert registry.has_component_of_type(StubA) is False

    def test_type_and_name_correct_type(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        assert registry.has_component_of_type(StubA, name="a") is True

    def test_type_and_name_wrong_type_raises(self, registry: Registry) -> None:
        registry.add_component("b", StubB())
        with pytest.raises(ValueError):
            registry.has_component_of_type(StubA, name="b")

    def test_type_and_name_not_found_raises(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            registry.has_component_of_type(StubA, name="missing")


class TestCacheService:
    def test_getter_raises_when_unset(self, registry: Registry) -> None:
        with pytest.raises(ValueError):
            _ = registry.cache_service

    def test_setter_assigns(self, registry: Registry) -> None:
        mock_cache = MagicMock()
        registry.cache_service = mock_cache
        assert registry.cache_service is mock_cache

    def test_setter_replaces_and_warns_on_a_second_set(self, registry: Registry, caplog: pytest.LogCaptureFixture) -> None:
        """Named caches made this an upsert: a cache can legitimately be swapped after startup.

        It warns because the usual way to get here is two calls to ``with_cache()``, and the
        second would otherwise take over the first with nothing said.
        """
        first, second = MagicMock(), MagicMock()
        registry.cache_service = first
        with caplog.at_level(logging.WARNING):
            registry.cache_service = second

        assert registry.cache_service is second
        assert "is being replaced by" in caplog.text

    def test_has_cache_false_when_unset(self, registry: Registry) -> None:
        assert registry.has_cache() is False

    def test_has_cache_true_when_set(self, registry: Registry) -> None:
        registry.cache_service = MagicMock()
        assert registry.has_cache() is True


class TestClear:
    def test_clear_components_empties_registry(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        registry.clear_components()
        assert not registry.has_component("a")

    def test_clear_removes_components_and_resets_cache(self, registry: Registry) -> None:
        mock_cache = MagicMock()
        registry.add_component("a", StubA())
        registry.cache_service = mock_cache

        registry.clear()

        assert not registry.has_component("a")
        assert not registry.has_cache()
        mock_cache.clear.assert_called_once()

    def test_clear_without_cache_does_not_raise(self, registry: Registry) -> None:
        registry.add_component("a", StubA())
        registry.clear()
        assert not registry.has_component("a")


class _Namespaced(StubBase):
    """A stub carrying the ``namespace`` attribute every real component has."""

    def __init__(self, namespace: str = "") -> None:
        self.namespace = namespace


@pytest.fixture
def grouped_registry() -> Registry:
    """Two agents owning the same component type, plus one shared at the root.

    Registered under the qualified names ``Component.__init__`` derives, because that is what
    the namespace-then-root fallback resolves through.
    """
    registry = Registry(StubBase)
    registry.add_component("orders_order_service", _Namespaced("orders"))
    registry.add_component("billing_order_service", _Namespaced("billing"))
    registry.add_component("shared_audit", _Namespaced(""))
    return registry


class TestNamespacedNameLookup:
    def test_a_bare_name_resolves_to_the_asking_namespace(self, grouped_registry: Registry) -> None:
        assert grouped_registry.get_component("order_service", "orders").namespace == "orders"

    def test_two_agents_get_their_own(self, grouped_registry: Registry) -> None:
        orders = grouped_registry.get_component("order_service", "orders")
        billing = grouped_registry.get_component("order_service", "billing")
        assert (orders.namespace, billing.namespace) == ("orders", "billing")

    def test_a_namespace_falls_back_to_the_root(self, grouped_registry: Registry) -> None:
        """Infrastructure stays shared: only what an agent owns is per-agent."""
        assert grouped_registry.get_component("shared_audit", "orders").namespace == ""

    def test_an_already_qualified_name_still_resolves(self, grouped_registry: Registry) -> None:
        """Qualifying it twice simply misses, and the bare lookup then finds it."""
        assert grouped_registry.get_component("orders_order_service", "orders").namespace == "orders"

    def test_a_bare_name_without_a_namespace_does_not_resolve(self, grouped_registry: Registry) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            grouped_registry.get_component("order_service")

    def test_the_error_names_where_it_looked(self, grouped_registry: Registry) -> None:
        with pytest.raises(ValueError, match="namespace 'orders' or at the root"):
            grouped_registry.get_component("missing", "orders")

    def test_has_component_follows_the_same_fallback(self, grouped_registry: Registry) -> None:
        assert grouped_registry.has_component("order_service", "orders") is True
        assert grouped_registry.has_component("order_service", "") is False
        assert grouped_registry.has_component("shared_audit", "orders") is True


class TestNamespacedTypeLookup:
    def test_no_namespace_returns_every_namespace(self, grouped_registry: Registry) -> None:
        """The default has to stay "everything" -- build() iterating handlers needs all of them."""
        assert len(grouped_registry.get_components_by_type(_Namespaced)) == 3

    def test_a_namespace_returns_only_that_agent(self, grouped_registry: Registry) -> None:
        found = grouped_registry.get_components_by_type(_Namespaced, "orders")
        assert [component.namespace for component in found] == ["orders"]

    def test_the_root_is_a_namespace_like_any_other(self, grouped_registry: Registry) -> None:
        found = grouped_registry.get_component_names_by_type(_Namespaced, "")
        assert found == ["shared_audit"]

    def test_filtering_is_by_attribute_not_by_name(self, grouped_registry: Registry) -> None:
        """A component registered under an explicit name is still attributed correctly."""
        grouped_registry.add_component("legacy_name", _Namespaced("orders"))
        found = grouped_registry.get_component_names_by_type(_Namespaced, "orders")
        assert sorted(found) == ["legacy_name", "orders_order_service"]

    def test_a_class_lookup_prefers_the_asking_namespace(self, grouped_registry: Registry) -> None:
        assert grouped_registry.get_component(_Namespaced, "billing").namespace == "billing"

    def test_a_class_lookup_without_a_namespace_refuses_to_guess(self, grouped_registry: Registry) -> None:
        """Handing an agent a neighbour's collaborator is the failure the namespace prevents."""
        with pytest.raises(ValueError, match="Multiple components"):
            grouped_registry.get_component(_Namespaced)

    def test_a_class_lookup_is_ambiguous_within_one_namespace_too(self, grouped_registry: Registry) -> None:
        grouped_registry.add_component("orders_second", _Namespaced("orders"))
        with pytest.raises(ValueError, match="ambiguous"):
            grouped_registry.get_component(_Namespaced, "orders")

    def test_has_component_of_type_can_be_asked_per_namespace(self, grouped_registry: Registry) -> None:
        assert grouped_registry.has_component_of_type(_Namespaced, None, "orders") is True
        assert grouped_registry.has_component_of_type(_Namespaced, None, "shipping") is False


class TestC6:
    def test_the_registry_cannot_be_asked_which_namespaces_exist(self, grouped_registry: Registry) -> None:
        """C6: Component.registry is reachable from agent code, so this must not be answerable."""
        assert not hasattr(grouped_registry, "get_known_namespaces")


class TestNamedCaches:
    """Caches are looked up by name, and never substituted for one another (spec sec. 8)."""

    def test_a_cache_is_retrieved_under_the_name_it_was_added_with(self, registry: Registry) -> None:
        sessions = MagicMock()
        registry.add_cache("sessions", sessions)
        assert registry.get_cache("sessions") is sessions

    def test_an_unregistered_name_does_not_fall_back_to_the_default(self, registry: Registry) -> None:
        """Two agents asking for "sessions" must not silently be handed one store."""
        registry.add_cache("default", MagicMock())
        with pytest.raises(ValueError, match="No cache registered as 'sessions'"):
            registry.get_cache("sessions")

    def test_the_error_lists_what_is_registered(self, registry: Registry) -> None:
        registry.add_cache("sessions", MagicMock())
        with pytest.raises(ValueError, match=r"registered: sessions"):
            registry.get_cache("prompts")

    def test_the_error_says_none_when_nothing_is_registered(self, registry: Registry) -> None:
        with pytest.raises(ValueError, match=r"registered: none"):
            registry.get_cache("sessions")

    def test_caches_do_not_collide(self, registry: Registry) -> None:
        first, second = MagicMock(), MagicMock()
        registry.add_cache("sessions", first)
        registry.add_cache("prompts", second)
        assert (registry.get_cache("sessions"), registry.get_cache("prompts")) == (first, second)

    def test_has_cache_asks_about_one_name(self, registry: Registry) -> None:
        registry.add_cache("sessions", MagicMock())
        assert (registry.has_cache("sessions"), registry.has_cache("prompts"), registry.has_cache()) == (True, False, False)

    def test_the_default_name_is_what_the_alias_reads(self, registry: Registry) -> None:
        cache = MagicMock()
        registry.add_cache("default", cache)
        assert (registry.cache_service is cache, registry.has_cache()) == (True, True)

    def test_the_alias_writes_the_default_name(self, registry: Registry) -> None:
        cache = MagicMock()
        registry.cache_service = cache
        assert registry.get_cache("default") is cache

    def test_get_all_caches_returns_a_copy(self, registry: Registry) -> None:
        """The health checks and the management endpoints iterate this; they must not mutate it."""
        registry.add_cache("sessions", MagicMock())
        caches = registry.get_all_caches()
        caches["injected"] = MagicMock()
        assert registry.has_cache("injected") is False

    def test_clear_empties_and_clears_every_cache(self, registry: Registry) -> None:
        first, second = MagicMock(), MagicMock()
        registry.add_cache("default", first)
        registry.add_cache("sessions", second)

        registry.clear()

        first.clear.assert_called_once()
        second.clear.assert_called_once()
        assert registry.get_all_caches() == {}


class TestCachesPerAgent:
    """A cache belongs to the agent that declared it, and to no other (spec sec. 8, D3).

    The store is keyed on ``(namespace, name)``, so the name alone no longer identifies a
    cache. What each case below pins down is that there is **no route** from one agent to
    another's cache: not by name, not through the root, and not by enumeration.
    """

    def test_a_view_registers_for_its_own_agent(self, registry: Registry) -> None:
        """A component calls ``self.registry.add_cache(...)`` and names no namespace."""
        cache = MagicMock()
        registry.for_namespace("orders").add_cache("sessions", cache)
        assert registry.get_cache("sessions", namespace="orders") is cache

    def test_two_agents_may_both_declare_one_name(self, registry: Registry) -> None:
        orders, billing = MagicMock(), MagicMock()
        registry.add_cache("sessions", orders, namespace="orders")
        registry.add_cache("sessions", billing, namespace="billing")

        assert registry.for_namespace("orders").get_cache("sessions") is orders
        assert registry.for_namespace("billing").get_cache("sessions") is billing

    def test_one_name_registered_twice_for_one_agent_still_replaces(self, registry: Registry) -> None:
        """Two agents are not a collision; the same agent twice still is, and warns."""
        first, second = MagicMock(), MagicMock()
        registry.add_cache("sessions", first, namespace="orders")
        registry.add_cache("sessions", second, namespace="orders")
        assert registry.get_cache("sessions", namespace="orders") is second

    def test_an_agent_cannot_reach_a_neighbours_cache(self, registry: Registry) -> None:
        registry.add_cache("sessions", MagicMock(), namespace="orders")

        with pytest.raises(ValueError, match="No cache registered as 'sessions' for agent 'billing'"):
            registry.for_namespace("billing").get_cache("sessions")

    def test_an_agent_does_not_fall_back_to_the_root(self, registry: Registry) -> None:
        """Components resolve namespace-then-root; caches deliberately do not."""
        registry.add_cache("sessions", MagicMock())

        with pytest.raises(ValueError, match="for agent 'orders'"):
            registry.for_namespace("orders").get_cache("sessions")

    def test_the_root_does_not_see_an_agents_cache(self, registry: Registry) -> None:
        registry.add_cache("sessions", MagicMock(), namespace="orders")
        assert registry.get_all_caches() == {}
        assert registry.has_cache("sessions") is False

    def test_the_default_alias_is_per_agent(self, registry: Registry) -> None:
        orders, billing = MagicMock(), MagicMock()
        registry.for_namespace("orders").cache_service = orders
        registry.for_namespace("billing").cache_service = billing

        assert registry.for_namespace("orders").cache_service is orders
        assert registry.for_namespace("billing").cache_service is billing

    def test_the_alias_raises_for_an_agent_that_declared_none(self, registry: Registry) -> None:
        """This is the check ``idempotency_enabled`` fails on, and it is now per agent."""
        registry.for_namespace("orders").cache_service = MagicMock()

        with pytest.raises(ValueError, match="No cache service registered for agent 'billing'"):
            _ = registry.for_namespace("billing").cache_service

    def test_has_cache_answers_about_the_asking_agent(self, registry: Registry) -> None:
        registry.for_namespace("orders").cache_service = MagicMock()

        assert registry.for_namespace("orders").has_cache() is True
        assert registry.for_namespace("billing").has_cache() is False

    def test_get_all_caches_is_one_agents(self, registry: Registry) -> None:
        registry.add_cache("sessions", MagicMock(), namespace="orders")
        registry.add_cache("prompts", MagicMock(), namespace="billing")

        assert sorted(registry.get_all_caches("orders")) == ["sessions"]
        assert sorted(registry.for_namespace("billing").get_all_caches()) == ["prompts"]

    def test_cache_entries_carries_the_agent_as_data(self, registry: Registry) -> None:
        """As data, not as a prefix: a cache name may legally contain the separator."""
        orders, root = MagicMock(), MagicMock()
        registry.add_cache("v2.sessions", orders, namespace="orders")
        registry.add_cache("default", root)

        assert [(namespace, name) for namespace, name, _ in registry.cache_entries()] == [
            ("orders", "v2.sessions"),
            ("", "default"),
        ]

    def test_cache_entries_is_refused_on_a_view(self, registry: Registry) -> None:
        """C6: a view is what agent code holds, so it must not enumerate the neighbours."""
        registry.add_cache("sessions", MagicMock(), namespace="orders")

        with pytest.raises(RuntimeError, match="asked for every cache in the process"):
            registry.for_namespace("orders").cache_entries()

    def test_clear_clears_every_agents_cache(self, registry: Registry) -> None:
        orders, billing = MagicMock(), MagicMock()
        registry.add_cache("sessions", orders, namespace="orders")
        registry.add_cache("sessions", billing, namespace="billing")

        registry.clear()

        orders.clear.assert_called_once()
        billing.clear.assert_called_once()
        assert registry.cache_entries() == []


class TestExecutors:
    """One thread pool per namespace, created only when something actually needs one."""

    def test_no_pool_exists_until_one_is_asked_for(self, registry: Registry) -> None:
        """An application with no blocking work must run with no extra threads (spec sec. 4.3)."""
        assert registry._executors == {}

    def test_the_first_call_creates_and_the_second_reuses(self, registry: Registry) -> None:
        first = registry.get_or_create_executor("orders")
        assert registry.get_or_create_executor("orders") is first

    def test_each_namespace_gets_its_own(self, registry: Registry) -> None:
        """One agent exhausting its pool must not stall another's blocking work."""
        assert registry.get_or_create_executor("orders") is not registry.get_or_create_executor("billing")

    def test_the_root_is_a_namespace_like_any_other(self, registry: Registry) -> None:
        assert registry.get_or_create_executor() is registry.get_or_create_executor("")

    def test_the_creating_call_sizes_the_pool(self, registry: Registry) -> None:
        assert registry.get_or_create_executor("orders", 3)._max_workers == 3

    def test_a_later_size_is_ignored_because_a_live_pool_cannot_be_resized(self, registry: Registry) -> None:
        registry.get_or_create_executor("orders", 3)
        assert registry.get_or_create_executor("orders", 9)._max_workers == 3

    def test_threads_are_named_after_their_namespace(self, registry: Registry) -> None:
        """So a stack dump or a profiler says which agent a blocked thread belongs to."""
        assert registry.get_or_create_executor("orders")._thread_name_prefix == "blueprint-orders"

    def test_shutdown_closes_and_forgets_every_pool(self, registry: Registry) -> None:
        executor = registry.get_or_create_executor("orders")
        registry.shutdown_executors()
        assert registry._executors == {}
        assert executor._shutdown is True

    def test_clear_shuts_the_pools_down_too(self, registry: Registry) -> None:
        """Otherwise a test suite building many applications accumulates thread pools."""
        executor = registry.get_or_create_executor("orders")
        registry.clear()
        assert registry._executors == {}
        assert executor._shutdown is True


class TestNamespaceViews:
    """A view answers as one agent, so a call site never has to name a namespace."""

    def test_the_root_namespace_is_the_registry_itself(self, grouped_registry: Registry) -> None:
        """Not an optimisation: the root namespace *is* the unscoped registry."""
        assert grouped_registry.for_namespace("") is grouped_registry

    def test_views_are_cached(self, grouped_registry: Registry) -> None:
        assert grouped_registry.for_namespace("orders") is grouped_registry.for_namespace("orders")

    def test_a_view_shares_the_one_component_store(self, grouped_registry: Registry) -> None:
        """One registry per process; a view is a lens on it, not a copy of it."""
        view = grouped_registry.for_namespace("orders")
        assert view._components is grouped_registry._components
        assert view._caches is grouped_registry._caches

    def test_a_view_reports_the_namespace_it_answers_as(self, grouped_registry: Registry) -> None:
        assert grouped_registry.for_namespace("orders").default_namespace == "orders"
        assert grouped_registry.default_namespace is None

    def test_a_view_cannot_mint_another_agents_view(self, grouped_registry: Registry) -> None:
        """C6: it would hand every component a route to its neighbours."""
        view = grouped_registry.for_namespace("orders")
        with pytest.raises(RuntimeError, match="not from another agent"):
            view.for_namespace("billing")

    def test_an_omitted_namespace_means_this_agent(self, grouped_registry: Registry) -> None:
        view = grouped_registry.for_namespace("orders")
        assert view.get_component("order_service").namespace == "orders"

    def test_an_omitted_namespace_still_falls_back_to_the_root(self, grouped_registry: Registry) -> None:
        assert grouped_registry.for_namespace("orders").get_component("shared_audit").namespace == ""

    def test_a_class_lookup_on_a_view_finds_this_agents_instance(self, grouped_registry: Registry) -> None:
        assert grouped_registry.for_namespace("billing").get_component(_Namespaced).namespace == "billing"

    def test_a_class_lookup_on_a_view_falls_back_to_the_root(self, grouped_registry: Registry) -> None:
        """The candidates must be gathered unfiltered, or the fallback could never fire."""
        registry = Registry(StubBase)
        registry.add_component("shared_audit", _Namespaced(""))
        assert registry.for_namespace("orders").get_component(_Namespaced).namespace == ""

    def test_a_plural_lookup_on_a_view_returns_only_this_agent(self, grouped_registry: Registry) -> None:
        found = grouped_registry.for_namespace("orders").get_components_by_type(_Namespaced)
        assert [component.namespace for component in found] == ["orders"]

    def test_an_explicit_namespace_overrides_the_view(self, grouped_registry: Registry) -> None:
        view = grouped_registry.for_namespace("orders")
        assert view.get_component("order_service", "billing").namespace == "billing"

    def test_the_application_registry_still_sees_everything(self, grouped_registry: Registry) -> None:
        """build() and the lifespan hold the unscoped registry and must keep iterating all of it."""
        assert len(grouped_registry.get_components_by_type(_Namespaced)) == 3
