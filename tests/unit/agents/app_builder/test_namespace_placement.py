"""A component ends up in the right agent without anyone naming a namespace.

The one thing the whole design rests on. No component, no constructor, and no line a developer
writes mentions a namespace: a declaration takes whichever namespace is in force where it is
recorded, which is the root for a standalone application and the agent's own for a declaration
a group is replaying. So most of these assert on the registry key a component got, which is the
only externally visible consequence of the namespace it was built in.

``namespace_scope`` stands in for the group here on purpose: it is exactly what
``AgentGroup.assemble`` opens, and using it keeps these cases about placement rather than about
collection, which ``tests/unit/agents/test_agent_group.py`` covers.
"""

from pathlib import Path
from typing import Any

import pytest

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import ROOT_NAMESPACE, current_namespace, namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.services.service_base import ServiceBase

from .conftest import StubHandler, realize


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


def declared_in(builder: AppBuilder, namespace: str, declare: Any) -> AppBuilder:
    """Record ``declare(builder)`` with ``namespace`` in force, as a group's replay would."""
    with namespace_scope(namespace):
        declare(builder)
    return builder


class TestTheAmbientNamespaceDecidesPlacement:
    def test_a_namespace_qualifies_the_registry_name(self, two_agent_config: Config) -> None:
        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(OrderService))

        realize(builder)

        assert component_names() == ["orders_order_service"]

    def test_the_namespace_reaches_the_component_itself(self, two_agent_config: Config) -> None:
        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(OrderService))

        realize(builder)

        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("orders_order_service").namespace == "orders"

    def test_it_is_captured_at_the_call_not_at_construction(self, two_agent_config: Config) -> None:
        """``realize`` runs with no scope in force, so a namespace read late would be the root."""
        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(OrderService))

        assert current_namespace() == ROOT_NAMESPACE
        realize(builder)

        assert component_names() == ["orders_order_service"]

    def test_the_namespace_is_not_forwarded_to_the_constructor(self, two_agent_config: Config) -> None:
        """StrictService takes no namespace argument, which is what every project's code looks like."""
        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(StrictService, retries=3))

        realize(builder)

        registry = Component.shared_registry
        assert registry is not None
        built = registry.get_component("orders_strict_service")
        assert (built.namespace, built.retries) == ("orders", 3)

    def test_no_scope_keeps_todays_names(self, two_agent_config: Config) -> None:
        realize(AppBuilder(two_agent_config).with_service(OrderService))

        assert component_names() == ["order_service"]

    def test_the_scope_is_restored_afterwards(self, two_agent_config: Config) -> None:
        declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(OrderService))

        assert current_namespace() == ROOT_NAMESPACE

    @pytest.mark.parametrize(
        ("method", "target", "expected"),
        [
            ("with_handler", StubHandler, "orders_stub_handler"),
            ("with_service", OrderService, "orders_order_service"),
            ("with_rest_api", OrderApi, "orders_order_api"),
        ],
    )
    def test_every_method_places_into_the_namespace(self, two_agent_config: Config, method: str, target: Any, expected: str) -> None:
        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: getattr(b, method)(target))

        realize(builder)

        assert component_names() == [expected]

    def test_there_is_no_namespace_keyword(self, two_agent_config: Config) -> None:
        """It existed only for NamespaceBuilder. The scope carries the namespace instead."""
        with pytest.raises(TypeError):
            AppBuilder(two_agent_config).with_service(OrderService, namespace="orders")  # type: ignore[call-arg]

    def test_the_handler_type_check_still_fires(self, two_agent_config: Config) -> None:
        with pytest.raises(TypeError, match="EventHandlerBase subclass"):
            AppBuilder(two_agent_config).with_handler(OrderService)  # type: ignore[type-var]


class TestExplicitNames:
    def test_an_explicit_name_is_qualified_with_the_namespace(self, two_agent_config: Config) -> None:
        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(OrderService, name="db"))

        realize(builder)

        assert component_names() == ["orders_db"]

    def test_an_explicit_name_at_the_root_is_unchanged(self, two_agent_config: Config) -> None:
        realize(AppBuilder(two_agent_config).with_service(OrderService, name="db"))

        assert component_names() == ["db"]

    def test_the_bare_name_still_finds_it(self, two_agent_config: Config) -> None:
        """Registry._lookup tries '<namespace>_<name>' first, so qualifying costs the caller nothing."""
        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(OrderService, name="db"))

        realize(builder)

        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("db", namespace="orders").namespace == "orders"


class TestAlreadyBuiltInstances:
    def test_an_instance_is_refused_for_another_namespace(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        instance = OrderService()

        with pytest.raises(ValueError, match="cannot change namespace"):
            declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(instance))

    def test_the_refusal_names_both_namespaces_and_the_method(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        instance = OrderService()

        with pytest.raises(ValueError, match=r"with_service\(\).*'orders'.*'<root>'"):
            declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(instance))

    def test_an_instance_from_the_same_namespace_is_accepted(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        with namespace_scope("orders"):
            instance = OrderService()

        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(instance))

        realize(builder)

        assert component_names() == ["orders_order_service"]

    def test_an_instance_at_the_root_is_unaffected(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        instance = OrderService()

        realize(AppBuilder(two_agent_config).with_service(instance))

        assert component_names() == ["order_service"]


class TestHostedAgents:
    def test_a_single_agent_application_hosts_none(self, two_agent_config: Config) -> None:
        assert AppBuilder(two_agent_config).with_service(OrderService).namespaces == ()

    def test_host_agent_records_them_in_order(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config)
        builder.host_agent("orders")
        builder.host_agent("billing")

        assert builder.namespaces == ("orders", "billing")

    def test_hosting_one_agent_twice_is_refused(self, two_agent_config: Config) -> None:
        """Two agents cannot share a name: the name is what tells them apart everywhere."""
        builder = AppBuilder(two_agent_config)
        builder.host_agent("orders")

        with pytest.raises(ValueError, match="already hosted by this process"):
            builder.host_agent("orders")

    def test_the_root_is_refused(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="names no agent"):
            AppBuilder(two_agent_config).host_agent("")

    def test_an_illegal_name_is_refused(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="legal namespace"):
            AppBuilder(two_agent_config).host_agent("Orders")

    def test_it_returns_the_builder(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config)
        assert builder.host_agent("orders") is builder

    def test_a_scoped_declaration_is_not_a_hosted_agent(self, two_agent_config: Config) -> None:
        """``namespaces`` is what the builder was *told* to host, and a declaration is not that.

        Recording it there would make one scoped ``with_service`` enough to make 'orders' an
        agent of the group, and the code that iterates the list -- the startup log, the
        readiness policy -- would then report an agent nobody deployed.
        """
        builder = declared_in(AppBuilder(two_agent_config), "orders", lambda b: b.with_service(OrderService))

        assert builder.namespaces == ()


class TestTheDeletedSurfaces:
    """Four duplication sites became one. These pin that the other three are gone."""

    def test_there_is_no_agent_registration(self) -> None:
        import blueprint.agents.app_builder as module

        assert not hasattr(module, "AgentRegistration")
        assert not hasattr(module, "RegisteredComponent")

    def test_there_is_no_namespace_builder(self) -> None:
        import blueprint.agents.app_builder as module

        assert not hasattr(module, "NamespaceBuilder")

    def test_the_builder_has_neither_with_namespace_nor_with_registration(self) -> None:
        assert not hasattr(AppBuilder, "with_namespace")
        assert not hasattr(AppBuilder, "with_registration")

    def test_they_are_not_exported(self) -> None:
        import blueprint.agents as package

        assert "AgentRegistration" not in package.__all__
        assert "NamespaceBuilder" not in package.__all__
