"""``build()`` wiring a transport per agent, against real components.

Three decisions are being pinned down. Which agents get a client -- one per agent that consumes
or publishes, and none for an agent that does neither (spec sec. 6). Which get an endpoint --
one per agent that consumes, so each subscribes on its own behalf (spec sec. 7.6). And that a
single-agent application still gets exactly one of each, at the root.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from blueprint.agents.app_builder import AgentRegistration, AppBuilder
from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import ROOT_NAMESPACE
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.io.api.eventing.nats import NatsEventing
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.services.eventing.event_publishing_service import EventPublishingService
from blueprint.agents.services.service_base import ServiceBase


class OrderHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    def get_subscribed_topics(self) -> list[str]:
        return ["orders.created"]

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        return None


class BillingHandler(OrderHandler):
    def get_subscribed_topics(self) -> list[str]:
        return ["invoices.raised"]


class QuietService(ServiceBase):
    """A service, so an agent can exist without consuming or publishing anything."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


def settings(tmp_path: Path, body: str) -> Config:
    path = tmp_path / "settings.toml"
    path.write_text(body.replace("\n        ", "\n"))
    return Config(settings_files=[str(path)], root_path=str(tmp_path))


@pytest.fixture
def nats_config(tmp_path: Path) -> Config:
    """A root and two agents on NATS, with publishing opted into by one agent only."""
    return settings(
        tmp_path,
        """
        [development]
        app_name = "root-app"
        app_port = 8000
        event_bus = "nats"

        [development.orders]
        app_name = "orders"

        [development.billing]
        app_name = "billing"

        [development.reporting]
        app_name = "reporting"
        event_publishing_enabled = true
        """,
    )


def registry_names(component_type: Any) -> list[str]:
    registry = Component.shared_registry
    assert registry is not None
    return sorted(registry.get_component_names_by_type(component_type))


def build(builder: AppBuilder) -> None:
    """Run build() with the FastAPI app construction stubbed out."""
    with patch("blueprint.agents.app_builder.FastAPI"):
        builder.build()


class TestOneClientPerConsumingAgent:
    def test_each_agent_gets_its_own_client(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))
        builder.with_namespace("billing", registration=AgentRegistration().with_handler(BillingHandler))

        build(builder)

        assert registry_names(NATSClient) == ["billing_nats_client", "orders_nats_client"]

    def test_a_single_agent_application_gets_one_client_at_the_root(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config).with_handler(OrderHandler)

        build(builder)

        assert registry_names(NATSClient) == ["nats_client"]

    def test_the_root_gets_no_client_when_it_has_nothing(self, nats_config: Config) -> None:
        """A grouped application usually has nothing at the root, and then the root pass is a no-op."""
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))

        build(builder)

        assert registry_names(NATSClient) == ["orders_nats_client"]

    def test_an_agent_that_neither_consumes_nor_publishes_gets_no_client(self, nats_config: Config) -> None:
        """Spec sec. 6: a connection for it is a readiness dependency on traffic that does not exist."""
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))
        builder.with_namespace("billing", registration=AgentRegistration().with_service(QuietService))

        build(builder)

        assert registry_names(NATSClient) == ["orders_nats_client"]

    def test_a_publish_only_agent_gets_a_client_and_no_endpoint(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config)
        builder.with_namespace("reporting", registration=AgentRegistration().with_service(QuietService))

        build(builder)

        assert registry_names(NATSClient) == ["reporting_nats_client"]
        assert builder._eventing_components == []

    def test_publishing_is_opted_into_per_agent(self, nats_config: Config) -> None:
        """C5: 'reporting.event_publishing_enabled' is on, and its neighbour's is not."""
        builder = AppBuilder(nats_config)

        assert builder._publishing_requested("reporting") is True
        assert builder._publishing_requested("billing") is False
        assert builder._publishing_requested(ROOT_NAMESPACE) is False


class TestOneEndpointPerConsumingAgent:
    def test_each_consuming_agent_gets_an_endpoint(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))
        builder.with_namespace("billing", registration=AgentRegistration().with_handler(BillingHandler))

        build(builder)

        assert sorted(component.namespace for component in builder._eventing_components) == ["billing", "orders"]

    def test_a_single_agent_application_gets_one_at_the_root(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config).with_handler(OrderHandler)

        build(builder)

        assert [component.namespace for component in builder._eventing_components] == [ROOT_NAMESPACE]
        assert isinstance(builder._eventing_components[0], NatsEventing)

    def test_an_application_with_no_handler_gets_none(self, nats_config: Config) -> None:
        build(AppBuilder(nats_config).with_service(QuietService))

        assert Component.shared_registry is not None
        assert registry_names(NATSClient) == []

    async def test_each_endpoint_subscribes_only_its_own_topics(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))
        builder.with_namespace("billing", registration=AgentRegistration().with_handler(BillingHandler))
        build(builder)

        with patch.object(NATSClient, "subscribe", new_callable=AsyncMock) as subscribe:
            for component in builder._eventing_components:
                await component.on_startup()

        subscribed = [sorted(call[0][0]) for call in subscribe.call_args_list]
        assert subscribed == [["orders.created"], ["invoices.raised"]]


class TestOnePublishingServicePerAgentWithAClient:
    def test_each_agent_with_a_client_gets_one(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))
        builder.with_namespace("billing", registration=AgentRegistration().with_handler(BillingHandler))

        build(builder)

        assert registry_names(EventPublishingService) == [
            "billing_event_publishing_service",
            "orders_event_publishing_service",
        ]

    def test_a_single_agent_application_gets_one_at_the_root(self, nats_config: Config) -> None:
        build(AppBuilder(nats_config).with_handler(OrderHandler))

        assert registry_names(EventPublishingService) == ["event_publishing_service"]

    def test_an_agent_without_a_client_gets_none(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders", registration=AgentRegistration().with_handler(OrderHandler))
        builder.with_namespace("billing", registration=AgentRegistration().with_service(QuietService))

        build(builder)

        assert registry_names(EventPublishingService) == ["orders_event_publishing_service"]


class TestHostedNamespaces:
    def test_a_single_agent_application_hosts_the_root_only(self, nats_config: Config) -> None:
        assert AppBuilder(nats_config).hosted_namespaces == (ROOT_NAMESPACE,)

    def test_the_root_comes_first_and_the_agents_in_order(self, nats_config: Config) -> None:
        builder = AppBuilder(nats_config)
        builder.with_namespace("orders").end().with_namespace("billing").end()

        assert builder.hosted_namespaces == (ROOT_NAMESPACE, "orders", "billing")


class TestPublishOptInWithoutATransport:
    def test_it_names_the_agent_that_asked(self, tmp_path: Path) -> None:
        config = settings(
            tmp_path,
            """
            [development]
            app_name = "root-app"
            app_port = 8000

            [development.reporting]
            app_name = "reporting"
            event_publishing_enabled = true
            """.replace("\n            ", "\n        "),
        )
        builder = AppBuilder(config)
        builder.with_namespace("reporting", registration=AgentRegistration().with_service(QuietService))

        with pytest.raises(ValueError, match="'reporting'"):
            build(builder)
