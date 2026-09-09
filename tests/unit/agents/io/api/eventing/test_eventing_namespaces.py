"""Per-agent topic subscription on the NATS transport (spec sec. 7.6).

The requirement being pinned down is that each ``(namespace, topic)`` pair is subscribed on its
own behalf: an agent subscribes to its own handlers' topics and its own configured list, and two
agents wanting the same topic both get it. The failure this guards against is a cross-agent
deduplication that silently drops one agent's subscription -- invisible to its author, who runs
that agent alone.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import ROOT_NAMESPACE, namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.io.api.eventing.nats import NatsEventing
from blueprint.agents.models.events import GenericCloudEvent


class TopicHandler(EventHandlerBase):
    """A handler that declares topics the way a project's handler does."""

    TOPICS: list[str] = []

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    def get_subscribed_topics(self) -> list[str]:
        return list(self.TOPICS)

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        return None


class OrderHandler(TopicHandler):
    TOPICS = ["orders.created"]


class BillingHandler(TopicHandler):
    TOPICS = ["invoices.raised"]


class SharedTopicHandler(TopicHandler):
    TOPICS = ["orders.created"]


@pytest.fixture
def two_agent_config(tmp_path: Path) -> Config:
    """A root and two agents, with a per-agent ``nats_subscriptions`` list for one of them."""
    settings = tmp_path / "settings.toml"
    content = """
        [development]
        app_name = "root-app"
        app_port = 8000
        event_bus = "nats"
        nats_subscriptions = ["shared.>"]

        [development.orders]
        app_name = "orders"
        nats_subscriptions = ["orders.legacy"]

        [development.billing]
        app_name = "billing"
        """
    settings.write_text(content.replace("\n        ", "\n"))
    config = Config(settings_files=[str(settings)], root_path=str(tmp_path))
    Component.configure(config)
    return config


class TestNatsSubscribesForOneAgent:
    async def test_it_subscribes_its_own_handlers_topics(self, two_agent_config: Config) -> None:
        with namespace_scope("orders"):
            OrderHandler()
            NATSClient(namespace="orders")
        endpoint = NatsEventing(namespace="orders")

        assert "orders.created" in endpoint._declared_topics()

    async def test_it_does_not_subscribe_another_agents_topics(self, two_agent_config: Config) -> None:
        with namespace_scope("orders"):
            OrderHandler()
        with namespace_scope("billing"):
            BillingHandler()

        assert NatsEventing(namespace="orders")._declared_topics() == ["orders.created", "orders.legacy"]

    async def test_two_agents_wanting_one_topic_both_get_it(self, two_agent_config: Config) -> None:
        """Spec sec. 7.6: both want the event, so neither subscription may be deduplicated away."""
        with namespace_scope("orders"):
            OrderHandler()
        with namespace_scope("billing"):
            SharedTopicHandler()

        orders = NatsEventing(namespace="orders")._declared_topics()
        billing = NatsEventing(namespace="billing")._declared_topics()

        assert "orders.created" in orders
        assert "orders.created" in billing

    async def test_a_topic_declared_twice_in_one_agent_is_subscribed_once(self, two_agent_config: Config) -> None:
        with namespace_scope("orders"):
            OrderHandler()
            SharedTopicHandler()

        assert NatsEventing(namespace="orders")._declared_topics().count("orders.created") == 1

    async def test_the_agents_own_subscription_list_is_read(self, two_agent_config: Config) -> None:
        """C5: 'orders.nats_subscriptions' wins over the root list, with no code saying so."""
        assert NatsEventing(namespace="orders")._declared_topics() == ["orders.legacy"]

    async def test_an_agent_without_its_own_list_falls_back_to_the_shared_one(self, two_agent_config: Config) -> None:
        assert NatsEventing(namespace="billing")._declared_topics() == ["shared.>"]

    async def test_handler_topics_come_before_configured_ones(self, two_agent_config: Config) -> None:
        with namespace_scope("orders"):
            OrderHandler()

        assert NatsEventing(namespace="orders")._declared_topics() == ["orders.created", "orders.legacy"]


class TestNatsResolvesItsOwnClient:
    async def test_it_takes_its_own_namespaces_client(self, two_agent_config: Config) -> None:
        with namespace_scope("orders"):
            orders_client = NATSClient(namespace="orders")
        with namespace_scope("billing"):
            NATSClient(namespace="billing")
        endpoint = NatsEventing(namespace="orders")

        with patch.object(NATSClient, "subscribe", new_callable=AsyncMock):
            await endpoint.on_startup()

        assert endpoint._client is orders_client

    async def test_a_root_endpoint_takes_the_root_client(self, two_agent_config: Config) -> None:
        """Unchanged for every single-agent application: one client, at the root."""
        root_client = NATSClient()
        endpoint = NatsEventing()

        with patch.object(NATSClient, "subscribe", new_callable=AsyncMock):
            await endpoint.on_startup()

        assert endpoint._client is root_client

    async def test_only_this_agents_topics_reach_the_client(self, two_agent_config: Config) -> None:
        with namespace_scope("orders"):
            OrderHandler()
            NATSClient(namespace="orders")
        with namespace_scope("billing"):
            BillingHandler()
        endpoint = NatsEventing(namespace="orders")

        with patch.object(NATSClient, "subscribe", new_callable=AsyncMock) as subscribe:
            await endpoint.on_startup()

        assert sorted(subscribe.call_args[0][0]) == ["orders.created", "orders.legacy"]


class TestNamespaceOwnership:
    def test_an_endpoint_defaults_to_the_root(self, two_agent_config: Config) -> None:
        assert NatsEventing().namespace == ROOT_NAMESPACE

    def test_an_endpoint_takes_the_namespace_it_is_given(self, two_agent_config: Config) -> None:
        assert NatsEventing(namespace="orders").namespace == "orders"

    def test_an_illegal_namespace_is_refused(self, two_agent_config: Config) -> None:
        with pytest.raises(ValueError, match="legal namespace"):
            NatsEventing(namespace="Orders")

    def test_endpoints_are_not_registered(self, two_agent_config: Config) -> None:
        """Two agents' endpoints would collide on the derived name, and nothing looks them up."""
        NatsEventing(namespace="orders")
        NatsEventing(namespace="billing")
        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component_names_by_type(NatsEventing) == []
