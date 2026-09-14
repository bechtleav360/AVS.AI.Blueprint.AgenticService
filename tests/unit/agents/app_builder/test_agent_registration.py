"""Unit tests for ``AgentRegistration`` and ``AppBuilder.with_registration``.

What these are really testing is the constraint the design exists for: one declaration, no
namespace anywhere in it or in the components it names, applied either alone or once per agent.
"""

from pathlib import Path
from typing import Any

import pytest

from blueprint.agents.app_builder import AgentRegistration, AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import ROOT_NAMESPACE, current_namespace
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


class ConfiguredService(ServiceBase):
    """A service that takes constructor arguments, to check they survive the round trip."""

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
        model_name = "root-model"

        [development.orders]
        app_name = "orders"
        model_name = "orders-model"

        [development.billing]
        app_name = "billing"
        """
    settings.write_text(content.replace("\n        ", "\n"))
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


def service_names() -> list[str]:
    registry = Component.shared_registry
    assert registry is not None
    return sorted(registry.get_component_names_by_type(ServiceBase))


class TestDeclaration:
    def test_nothing_is_built_when_a_component_is_declared(self) -> None:
        """The point of a registration: a component built now would predate every namespace."""
        AgentRegistration().with_service(OrderService)
        assert Component.shared_registry is None

    def test_declarations_are_kept_in_order(self) -> None:
        """Handler priority and scheduler wiring read this order."""
        registration = AgentRegistration().with_handler(StubHandler).with_service(OrderService)
        assert [(entry.kind, entry.target) for entry in registration.components] == [
            ("handler", StubHandler),
            ("service", OrderService),
        ]

    def test_the_fluent_calls_return_the_same_registration(self) -> None:
        registration = AgentRegistration()
        assert registration.with_service(OrderService) is registration

    def test_constructor_arguments_and_names_are_stored(self) -> None:
        registration = AgentRegistration().with_service(ConfiguredService, name="orders_svc", retries=3)
        entry = registration.components[0]
        assert (entry.name, entry.kwargs) == ("orders_svc", {"retries": 3})

    def test_there_is_no_with_cache(self) -> None:
        """A cache is process-wide and belongs to the AppBuilder that hosts the group."""
        assert not hasattr(AgentRegistration(), "with_cache")


class TestRejections:
    def test_an_already_built_component_is_refused(self, two_agent_config: Config) -> None:
        """It was built before any namespace existed, so it belongs to the root whoever declared it."""
        Component.configure(two_agent_config)
        service = OrderService()
        with pytest.raises(TypeError, match="as an instance"):
            AgentRegistration().with_service(service)

    def test_the_refusal_names_the_class_and_the_method(self, two_agent_config: Config) -> None:
        Component.configure(two_agent_config)
        with pytest.raises(TypeError, match=r"with_rest_api\(OrderApi, \.\.\.\)"):
            AgentRegistration().with_rest_api(OrderApi())

    @pytest.mark.parametrize("target", ["OrderService", 42, None])
    def test_something_that_cannot_be_called_is_refused(self, target: Any) -> None:
        with pytest.raises(TypeError, match="component class or a callable"):
            AgentRegistration().with_handler(target)


class TestApplyToOneAgent:
    def test_a_single_agent_application_registers_at_the_root(self, two_agent_config: Config) -> None:
        """Unchanged naming: this is what an existing project gets, whichever way it declares."""
        AppBuilder(two_agent_config).with_registration(AgentRegistration().with_service(OrderService))
        assert service_names() == ["order_service"]

    def test_applying_under_a_namespace_qualifies_the_name(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_registration(AgentRegistration().with_service(OrderService), "orders")
        assert service_names() == ["orders_order_service"]

    def test_with_registration_returns_the_builder(self, two_agent_config: Config) -> None:
        builder = AppBuilder(two_agent_config)
        assert builder.with_registration(AgentRegistration()) is builder

    def test_constructor_arguments_reach_the_component(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_registration(AgentRegistration().with_service(ConfiguredService, retries=3))
        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("configured_service").retries == 3

    def test_an_explicit_name_is_forwarded(self, two_agent_config: Config) -> None:
        AppBuilder(two_agent_config).with_registration(AgentRegistration().with_service(OrderService, name="svc"))
        assert service_names() == ["svc"]

    def test_an_illegal_namespace_is_refused(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="legal namespace"):
            AppBuilder(two_agent_config).with_registration(AgentRegistration().with_service(OrderService), "Orders")


class TestOneDeclarationTwoAgents:
    """The constraint, end to end: the same object applied twice, under two namespaces."""

    def test_one_declaration_becomes_two_independently_named_agents(self, two_agent_config: Config) -> None:
        registration = AgentRegistration().with_service(OrderService)
        builder = AppBuilder(two_agent_config)

        builder.with_registration(registration, "orders")
        builder.with_registration(registration, "billing")

        assert service_names() == ["billing_order_service", "orders_order_service"]

    def test_each_agent_reads_its_own_configuration(self, two_agent_config: Config) -> None:
        """C5 through the ambient namespace: neither the service nor the declaration mentions one."""
        registration = AgentRegistration().with_service(OrderService)
        builder = AppBuilder(two_agent_config)
        builder.with_registration(registration, "orders")
        builder.with_registration(registration, "billing")
        Component.configure(two_agent_config)

        registry = Component.shared_registry
        assert registry is not None
        orders = registry.get_component("orders_order_service")
        billing = registry.get_component("billing_order_service")

        assert (orders.config.get("model_name"), billing.config.get("model_name")) == ("orders-model", "root-model")
        assert (orders.config.get("app_name"), billing.config.get("app_name")) == ("orders", "billing")

    def test_the_namespace_is_left_behind_afterwards(self, two_agent_config: Config) -> None:
        """Otherwise the builder's own root components would join the last agent applied."""
        AppBuilder(two_agent_config).with_registration(AgentRegistration().with_service(OrderService), "orders")
        assert current_namespace() == ROOT_NAMESPACE


class TestFactories:
    def test_a_factory_is_called_inside_the_namespace(self, two_agent_config: Config) -> None:
        """The form the fluent AgentBuilder needs: a chain that cannot be a class plus kwargs."""
        registration = AgentRegistration().with_service(lambda: ConfiguredService(retries=7))

        AppBuilder(two_agent_config).with_registration(registration, "orders")

        registry = Component.shared_registry
        assert registry is not None
        built = registry.get_component("orders_configured_service")
        assert (built.namespace, built.retries) == ("orders", 7)

    def test_a_factory_sees_the_ambient_namespace_while_it_runs(self, two_agent_config: Config) -> None:
        seen: list[str] = []

        def build_service() -> OrderService:
            seen.append(current_namespace())
            return OrderService()

        AppBuilder(two_agent_config).with_registration(AgentRegistration().with_service(build_service), "orders")

        assert seen == ["orders"]

    def test_a_factory_is_not_called_at_declaration_time(self) -> None:
        calls: list[int] = []
        AgentRegistration().with_service(lambda: calls.append(1) or OrderService())
        assert calls == []
