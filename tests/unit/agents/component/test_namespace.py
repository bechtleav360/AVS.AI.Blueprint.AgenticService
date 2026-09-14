"""Unit tests for the namespace naming, validation and resolution helpers (P6)."""

import pytest

from blueprint.agents.component.namespace import (
    ROOT_LABEL,
    ROOT_NAMESPACE,
    current_namespace,
    display_segment,
    namespace_of,
    namespace_scope,
    qualified_component_name,
    resolve_for_namespace,
    validate_namespace,
)


class _Client:
    """Stand-in for a namespace-owned component."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace


class _Unnamespaced:
    """Stand-in for a component that predates namespaces."""


class TestQualifiedComponentName:
    def test_root_namespace_keeps_the_bare_name(self) -> None:
        assert qualified_component_name(ROOT_NAMESPACE, "nats_client") == "nats_client"

    def test_namespace_prefixes_the_name(self) -> None:
        assert qualified_component_name("orders", "nats_client") == "orders_nats_client"

    def test_two_namespaces_never_share_a_name(self) -> None:
        assert qualified_component_name("orders", "nats_client") != qualified_component_name("invoice", "nats_client")


class TestNamespaceOf:
    def test_reads_the_namespace_attribute(self) -> None:
        assert namespace_of(_Client("orders")) == "orders"

    def test_component_without_the_attribute_is_at_the_root(self) -> None:
        assert namespace_of(_Unnamespaced()) == ROOT_NAMESPACE

    def test_none_is_read_as_the_root(self) -> None:
        assert namespace_of(_Client(None)) == ROOT_NAMESPACE  # type: ignore[arg-type]


class TestResolveForNamespace:
    def test_own_namespace_wins_over_the_root(self) -> None:
        own, root = _Client("orders"), _Client(ROOT_NAMESPACE)
        assert resolve_for_namespace([root, own], "orders", description="client") is own

    def test_falls_back_to_the_root_when_the_namespace_has_none(self) -> None:
        root = _Client(ROOT_NAMESPACE)
        assert resolve_for_namespace([root, _Client("invoice")], "orders", description="client") is root

    def test_root_never_picks_up_a_namespaced_candidate(self) -> None:
        """A shared component must not silently attach to one agent's transport."""
        with pytest.raises(ValueError, match="No client is registered"):
            resolve_for_namespace([_Client("orders")], ROOT_NAMESPACE, description="client")

    def test_two_candidates_in_one_namespace_raise(self) -> None:
        with pytest.raises(ValueError, match="ambiguous"):
            resolve_for_namespace([_Client("orders"), _Client("orders")], "orders", description="client")

    def test_ambiguity_error_names_the_level_and_the_asker(self) -> None:
        with pytest.raises(ValueError, match="Namespace '<root>' has 2 clients.*namespace 'orders'"):
            resolve_for_namespace([_Client(ROOT_NAMESPACE), _Client(ROOT_NAMESPACE)], "orders", description="client")

    def test_nothing_registered_raises(self) -> None:
        with pytest.raises(ValueError, match="No client is registered for namespace 'orders'"):
            resolve_for_namespace([], "orders", description="client")


class TestValidateNamespace:
    """One alphabet, enforced where the namespace enters the framework."""

    def test_root_namespace_is_valid(self) -> None:
        assert validate_namespace(ROOT_NAMESPACE) == ROOT_NAMESPACE

    @pytest.mark.parametrize("namespace", ["orders", "orders_eu", "a", "agent2", "order_2_eu"])
    def test_legal_namespaces_pass_through_unchanged(self, namespace: str) -> None:
        assert validate_namespace(namespace) == namespace

    def test_hyphen_is_rejected_as_the_durable_separator(self) -> None:
        with pytest.raises(ValueError, match="separator in the JetStream durable name"):
            validate_namespace("orders-eu")

    @pytest.mark.parametrize("namespace", ["orders.eu", "orders*", "orders>", "<root>", "Orders", "my orders", "1st"])
    def test_illegal_alphabets_are_rejected(self, namespace: str) -> None:
        with pytest.raises(ValueError, match="not a legal namespace"):
            validate_namespace(namespace)

    def test_the_root_label_cannot_be_produced_by_a_legal_namespace(self) -> None:
        """This is what makes the placeholder a reserved form rather than a convention."""
        with pytest.raises(ValueError):
            validate_namespace(ROOT_LABEL)

    def test_padded_namespace_is_rejected_rather_than_trimmed(self) -> None:
        with pytest.raises(ValueError, match="surrounding whitespace"):
            validate_namespace("  orders  ")

    def test_whitespace_only_namespace_is_not_the_root(self) -> None:
        with pytest.raises(ValueError, match="is not the root namespace"):
            validate_namespace("   ")

    def test_the_error_names_the_offending_characters(self) -> None:
        with pytest.raises(ValueError, match="'A'"):
            validate_namespace("Agent")


class TestDisplaySegment:
    """Values the deployment owns are sanitised, not validated -- see the docstring for why."""

    def test_a_usable_value_survives(self) -> None:
        assert display_segment("eu-west-1", "<none>") == "eu-west-1"

    def test_dots_cannot_split_one_segment_into_several(self) -> None:
        assert display_segment("web-7.eu.internal", "<none>") == "web-7_eu_internal"

    def test_brackets_cannot_forge_a_placeholder(self) -> None:
        assert display_segment(ROOT_LABEL, "<none>") != ROOT_LABEL

    def test_whitespace_is_replaced(self) -> None:
        assert display_segment("my group", "<none>") == "my_group"

    def test_an_empty_value_becomes_the_placeholder(self) -> None:
        assert display_segment("   ", "<none>") == "<none>"


class TestAmbientNamespace:
    """The scope that lets a developer-written component be namespaced without saying so."""

    def test_the_root_is_in_force_by_default(self) -> None:
        """A single-agent application never enters a scope, so nothing may change for it."""
        assert current_namespace() == ROOT_NAMESPACE

    def test_a_scope_sets_the_namespace(self) -> None:
        with namespace_scope("orders"):
            assert current_namespace() == "orders"

    def test_the_scope_is_left_on_the_way_out(self) -> None:
        with namespace_scope("orders"):
            pass
        assert current_namespace() == ROOT_NAMESPACE

    def test_the_scope_is_left_even_when_the_block_raises(self) -> None:
        """A leaked namespace would attach the next agent, or a root component, to the wrong one."""
        with pytest.raises(RuntimeError):
            with namespace_scope("orders"):
                raise RuntimeError("component construction failed")
        assert current_namespace() == ROOT_NAMESPACE

    def test_scopes_restore_the_previous_namespace_not_the_root(self) -> None:
        with namespace_scope("orders"):
            with namespace_scope("billing"):
                assert current_namespace() == "billing"
            assert current_namespace() == "orders"

    def test_the_root_scope_is_a_no_op(self) -> None:
        with namespace_scope(ROOT_NAMESPACE):
            assert current_namespace() == ROOT_NAMESPACE

    def test_an_illegal_namespace_is_rejected_on_entry(self) -> None:
        """Reported against the registration that declared it, not the first component built."""
        with pytest.raises(ValueError, match="legal namespace"):
            with namespace_scope("Orders"):
                pass
        assert current_namespace() == ROOT_NAMESPACE

    def test_the_scope_yields_its_namespace(self) -> None:
        with namespace_scope("orders") as namespace:
            assert namespace == "orders"
