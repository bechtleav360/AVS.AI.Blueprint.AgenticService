"""Unit tests for the namespace-aware ``AppBuilder`` and for ``NamespaceBuilder``.

The behaviour under test is the one thing the whole design rests on: a component ends up in the
right agent without the component, its constructor, or the code that declares it ever mentioning
a namespace. So most of these assert on the registry key a component got, which is the only
externally visible consequence of the namespace it was built in.
"""

from pathlib import Path
from typing import Any

import pytest

from blueprint.agents.app_builder import AgentRegistration, AppBuilder, NamespaceBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import ROOT_NAMESPACE, current_namespace, namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.services.service_base import ServiceBase

from .conftest import StubHandler


class OrderService(ServiceBase):
    """A service written the way a project writes one: no namespace, no arguments."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class StrictService(ServiceBase):
    """A service whose constructor accepts exactly one argument and no namespace.

    The point of the signature: if the builder ever forwarded ``namespace`` to the component,
    constructing this would raise ``TypeError`` instead of registering.
    """

    def __init__(self, retries: int = 0) -> None:
        super().__init__()
        self.retries = retries

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class OrderApi(RestApiBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


@pytest.fixture
def two_agent_config(tmp_path: Path) -> Config:
    """A settings tree with a root and two agents, injected as the shared component config."""
    settings = tmp_path / "settings.toml"
    content = """
        [development]
        app_name = "root-app"
        app_port = 8000

        [development.orders]
        app_name = "orders"

        [development.billing]
        app_name = "billing"
        """
    settings.write_text(content.replace("\n        ", "\n"))
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


def component_names() -> list[str]:
    registry = Component.shared_registry
    assert registry is not None
    return sorted(registry.get_component_names_by_type(Component))


class TestNamespaceOnTheBuilderMethods:
    def test_a_namespace_qualifies_the_registry_name(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_service(OrderService, namespace="orders")
        assert component_names() == ["orders_order_service"]

    def test_the_namespace_reaches_the_component_itself(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_service(OrderService, namespace="orders")
        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("orders_order_service").namespace == "orders"

    def test_the_namespace_is_not_forwarded_to_the_constructor(self, two_agent_config: Config) -> None:
        """StrictService takes no namespace argument, which is what every project's code looks like."""
        AppBuilder(two_agent_config).with_service(StrictService, namespace="orders", retries=3)
        registry = Component.shared_registry
        assert registry is not None
        built = registry.get_component("orders_strict_service")
        assert (built.namespace, built.retries) == ("orders", 3)

    def test_no_namespace_keeps_todays_names(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_service(OrderService)
        assert component_names() == ["order_service"]

    def test_the_default_does_not_reset_an_ambient_namespace(self, two_agent_config: Config) -> None:
        """The trap: ``namespace_scope("")`` *sets* the root, so the default must not open a scope.

        This is the path ``AgentRegistration.apply`` takes -- it opens one scope per agent and
        then calls these methods without a namespace argument.
        """
        builder = AppBuilder(two_agent_config)
        with namespace_scope("orders"):
            builder.with_service(OrderService)
        assert component_names() == ["orders_order_service"]

    def test_an_explicit_namespace_wins_over_the_ambient_one(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config)
        with namespace_scope("orders"):
            builder.with_service(OrderService, namespace="billing")
        assert component_names() == ["billing_order_service"]

    def test_the_ambient_namespace_is_restored_afterwards(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_service(OrderService, namespace="orders")
        assert current_namespace() == ROOT_NAMESPACE

    @pytest.mark.parametrize(
        ("method", "target", "expected"),
        [
            ("with_handler", StubHandler, "orders_stub_handler"),
            ("with_service", OrderService, "orders_order_service"),
            ("with_rest_api", OrderApi, "orders_order_api"),
        ],
    )
    def test_every_method_takes_a_namespace(self, two_agent_config: Config, method: str, target: Any, expected: str) -> None:
        builder = AppBuilder(two_agent_config)
        getattr(builder, method)(target, namespace="orders")
        assert component_names() == [expected]

    def test_an_illegal_namespace_is_refused(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="legal namespace"):
            AppBuilder(two_agent_config).with_service(OrderService, namespace="Orders")

    def test_the_handler_type_check_still_fires(self, two_agent_config: Config) -> None:
        with pytest.raises(TypeError, match="EventHandlerBase subclass"):
            AppBuilder(two_agent_config).with_handler(OrderService, namespace="orders")  # type: ignore[type-var]


class TestExplicitNames:
    def test_an_explicit_name_is_qualified_with_the_namespace(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_service(OrderService, name="db", namespace="orders")
        assert component_names() == ["orders_db"]

    def test_an_explicit_name_at_the_root_is_unchanged(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_service(OrderService, name="db")
        assert component_names() == ["db"]

    def test_one_declaration_with_an_explicit_name_serves_two_agents(self, two_agent_config: Config) -> None:
        """Unqualified, the second agent would collide on the one literal name and fail to build."""
        registration = AgentRegistration().with_service(OrderService, name="db")
        builder = AppBuilder(two_agent_config)

        builder.with_namespace("orders", registration=registration)
        builder.with_namespace("billing", registration=registration)

        assert component_names() == ["billing_db", "orders_db"]

    def test_the_bare_name_still_finds_it(self, two_agent_config: Config) -> None:
        """Registry._lookup tries '<namespace>_<name>' first, so qualifying costs the caller nothing."""
        AppBuilder(two_agent_config).with_service(OrderService, name="db", namespace="orders")
        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("db", namespace="orders").namespace == "orders"


class TestAlreadyBuiltInstances:
    def test_an_instance_is_refused_for_another_namespace(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        instance = OrderService()

        with pytest.raises(ValueError, match="cannot change namespace"):
            AppBuilder(two_agent_config).with_service(instance, namespace="orders")

    def test_the_refusal_names_both_namespaces_and_the_method(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        instance = OrderService()

        with pytest.raises(ValueError, match=r"with_service\(\).*'orders'.*'<root>'"):
            AppBuilder(two_agent_config).with_service(instance, namespace="orders")

    def test_an_instance_from_the_same_namespace_is_accepted(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        with namespace_scope("orders"):
            instance = OrderService()

        AppBuilder(two_agent_config).with_service(instance, namespace="orders")
        assert component_names() == ["orders_order_service"]

    def test_an_instance_at_the_root_is_unaffected(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        instance = OrderService()

        AppBuilder(two_agent_config).with_service(instance)
        assert component_names() == ["order_service"]


class TestWithNamespace:
    def test_a_registration_keeps_the_chain_on_the_builder(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config)
        returned = builder.with_namespace("orders", registration=AgentRegistration().with_service(OrderService))
        assert returned is builder
        assert component_names() == ["orders_order_service"]

    def test_no_registration_opens_a_namespace_block(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config)
        opened = builder.with_namespace("orders")
        assert isinstance(opened, NamespaceBuilder)
        assert opened.namespace == "orders"

    def test_the_root_namespace_is_refused(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="names no agent"):
            AppBuilder(two_agent_config).with_namespace("")

    def test_an_illegal_namespace_is_refused(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="legal namespace"):
            AppBuilder(two_agent_config).with_namespace("Orders")

    def test_the_ambient_namespace_is_left_behind(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_namespace("orders", registration=AgentRegistration().with_service(OrderService))
        assert current_namespace() == ROOT_NAMESPACE


class TestDeclaredNamespaces:
    def test_a_single_agent_application_declares_none(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config).with_service(OrderService)
        assert builder.namespaces == ()

    def test_declaration_order_is_kept(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config)
        builder.with_namespace("orders").end().with_namespace("billing").end()
        assert builder.namespaces == ("orders", "billing")

    def test_declaring_one_namespace_twice_is_refused(self, two_agent_config: Config) -> None:
        """Two agents cannot share a name: the name is what tells them apart everywhere."""
        builder = AppBuilder(two_agent_config)
        builder.with_namespace("orders", registration=AgentRegistration())

        with pytest.raises(ValueError, match="already hosted by this process"):
            builder.with_namespace("orders", registration=AgentRegistration().with_service(OrderService))

    def test_the_refusal_points_at_composing_one_registration(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config).with_namespace("orders").end()

        with pytest.raises(ValueError, match=r"single\s+AgentRegistration"):
            builder.with_namespace("orders")

    def test_a_tagged_with_call_is_not_a_declaration(self, two_agent_config: Config) -> None:
        """``namespaces`` is what the builder was *told* to host; a tagged call is not that.

        Recording it there would make ``with_service(X, namespace="orders")`` enough to make
        'orders' an agent of the group, and phases that iterate the list -- the startup log,
        the readiness policy -- would then report an agent nobody declared.
        """
        builder = AppBuilder(two_agent_config).with_service(OrderService, namespace="orders")
        assert builder.namespaces == ()


class TestNamespaceBlock:
    def test_every_call_lands_in_the_namespace(self, two_agent_config: Config) -> None:
        (
            AppBuilder(two_agent_config)
            .with_namespace("orders")
            .with_service(OrderService)
            .with_handler(StubHandler)
            .with_rest_api(OrderApi)
            .end()
        )
        assert component_names() == ["orders_order_api", "orders_order_service", "orders_stub_handler"]

    def test_the_calls_chain_on_the_block(self, two_agent_config: Config) -> None:
        block = AppBuilder(two_agent_config).with_namespace("orders")
        assert block.with_service(OrderService) is block

    def test_end_returns_the_parent_builder(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config)
        assert builder.with_namespace("orders").end() is builder

    def test_two_blocks_build_two_independent_agents(self, two_agent_config: Config) -> None:
        (
            AppBuilder(two_agent_config)
            .with_namespace("orders")
            .with_service(OrderService)
            .end()
            .with_namespace("billing")
            .with_service(OrderService)
            .end()
        )
        assert component_names() == ["billing_order_service", "orders_order_service"]

    def test_a_registration_can_be_applied_inside_a_block(self, two_agent_config: Config) -> None:
        block = AppBuilder(two_agent_config).with_namespace("orders")
        block.with_registration(AgentRegistration().with_service(OrderService))
        assert component_names() == ["orders_order_service"]

    def test_constructor_arguments_survive_the_delegation(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_namespace("orders").with_service(StrictService, retries=5).end()
        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("orders_strict_service").retries == 5

    def test_there_is_no_with_cache(self) -> None:
        """A cache belongs to the process, not to an agent (spec sec. 8)."""
        assert not hasattr(NamespaceBuilder, "with_cache")
