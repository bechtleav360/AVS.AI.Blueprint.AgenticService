"""One Dapr endpoint routing deliveries to the agents that want them.

Dapr fixes both of its paths: the sidecar fetches the subscription document from
``GET /dapr/subscribe`` and posts deliveries where that document says. So a grouped process
cannot give each agent its own endpoint -- there is one, at the root, and it does in the process
what the broker does for NATS: tell the sidecar about each topic once, then fan each delivery out
to every agent that declared that topic.

The cases below are the routing table, the fan-out, and the single acknowledgement a fan-out has
to collapse to.
"""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from blueprint.agents.clients.io.dapr_client import DaprClient
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import ROOT_NAMESPACE, namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.models.errors import CriticalHandlerError, RetryableHandlerError
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.services.eventing.event_processing_service import EventProcessingService

CALLS: list[str] = []
"""Which agents' handlers ran, in order. Reset by the ``calls`` fixture."""


class RecordingHandler(EventHandlerBase):
    """A handler that records the agent it ran for, and optionally fails."""

    TOPICS: list[str] = []
    FAILURE: Exception | None = None

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    def get_subscribed_topics(self) -> list[str]:
        return list(self.TOPICS)

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        CALLS.append(self.namespace)
        if self.FAILURE is not None:
            raise self.FAILURE
        return {"handled_by": self.namespace}


class OrderHandler(RecordingHandler):
    TOPICS = ["orders.created"]


class BillingHandler(RecordingHandler):
    TOPICS = ["orders.created", "invoices.raised"]


class ShippingHandler(RecordingHandler):
    TOPICS = ["shipments.booked"]


class RetryingHandler(RecordingHandler):
    TOPICS = ["orders.created"]
    FAILURE = RetryableHandlerError(status="busy", reason="try again")


class DroppingHandler(RecordingHandler):
    TOPICS = ["orders.created"]
    FAILURE = CriticalHandlerError(status="broken", reason="give up")


@pytest.fixture(autouse=True)
def calls() -> list[str]:
    CALLS.clear()
    return CALLS


@pytest.fixture
def config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "root-app"\napp_port = 8000\nevent_bus = "dapr"\n\n'
        '[development.orders]\napp_name = "orders"\n\n'
        '[development.billing]\napp_name = "billing"\n\n'
        '[development.shipping]\napp_name = "shipping"\n'
    )
    loaded = Config(settings_files=[str(settings)], root_path=str(tmp_path))
    Component.configure(loaded)
    return loaded


def event(event_type: str = "test.event") -> GenericCloudEvent:
    return GenericCloudEvent.model_construct(id="evt-1", type=event_type, source="/tests")


def build_agents(**handlers: type[RecordingHandler]) -> DaprEventing:
    """Register one handler per named agent, then return the process's Dapr endpoint."""
    for namespace, handler_type in handlers.items():
        with namespace_scope(namespace):
            handler_type()
    EventProcessingService()
    return DaprEventing()


class TestTheRoutingTable:
    def test_each_agents_topics_are_keyed_by_its_namespace(self, config: Config) -> None:
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)

        assert endpoint._topics_by_agent() == {
            "orders": ["orders.created"],
            "billing": ["orders.created", "invoices.raised"],
        }

    def test_the_document_is_the_union_deduplicated(self, config: Config) -> None:
        """The sidecar delivers a topic to the application once, so it is told once."""
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)

        assert sorted(endpoint._declared_topics()) == ["invoices.raised", "orders.created"]

    async def test_the_subscription_document_carries_the_union(self, config: Config) -> None:
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)

        document = await endpoint.subscribe()

        assert sorted(entry["topic"] for entry in document) == ["invoices.raised", "orders.created"]

    async def test_every_route_stays_at_the_fixed_path(self, config: Config) -> None:
        """The sidecar posts where the document says, and the endpoint is not prefixed."""
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)

        document = await endpoint.subscribe()

        assert all(entry["route"] == f"/events/{entry['topic']}" for entry in document)

    def test_an_agent_that_declared_nothing_is_absent(self, config: Config) -> None:
        endpoint = build_agents(orders=OrderHandler)
        with namespace_scope("billing"):
            RecordingHandler()  # declares no topic

        assert "billing" not in endpoint._topics_by_agent()


class TestAgentsForATopic:
    def test_one_declaring_agent(self, config: Config) -> None:
        endpoint = build_agents(orders=OrderHandler, shipping=ShippingHandler)

        assert endpoint._agents_for("shipments.booked") == ("shipping",)

    def test_two_agents_declaring_one_topic_both_appear(self, config: Config) -> None:
        """Spec sec. 7.6 for the in-process case: both want the event, so both get it."""
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)

        assert sorted(endpoint._agents_for("orders.created")) == ["billing", "orders"]

    def test_an_undeclared_topic_reaches_every_agent_with_handlers(self, config: Config) -> None:
        """The same rule as the dispatch index: an absent declaration narrows nothing.

        This is the path a topic declared outside the application takes --
        ``dapr_declarative_subscriptions`` leaves the framework with no topic list at all.
        """
        endpoint = build_agents(orders=OrderHandler, shipping=ShippingHandler)

        assert sorted(endpoint._agents_for("nobody.declared.this")) == ["orders", "shipping"]

    def test_a_single_agent_application_resolves_to_the_root(self, config: Config) -> None:
        endpoint = build_agents()
        RecordingHandler()

        assert endpoint._agents_for("anything") == (ROOT_NAMESPACE,)

    def test_no_handlers_at_all_resolves_to_the_root(self, config: Config) -> None:
        endpoint = build_agents()

        assert endpoint._agents_for("anything") == (ROOT_NAMESPACE,)


class TestFanOut:
    async def test_both_declaring_agents_handle_the_delivery(self, config: Config) -> None:
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)

        await endpoint.publish("orders.created", event())

        assert sorted(CALLS) == ["billing", "orders"]

    async def test_a_non_declaring_agent_is_not_offered_it(self, config: Config) -> None:
        endpoint = build_agents(orders=OrderHandler, shipping=ShippingHandler)

        await endpoint.publish("orders.created", event())

        assert CALLS == ["orders"]

    async def test_a_single_agent_application_dispatches_once(self, config: Config) -> None:
        endpoint = build_agents()
        RecordingHandler()

        await endpoint.publish("anything", event())

        assert CALLS == [ROOT_NAMESPACE]

    async def test_one_agent_failing_does_not_stop_the_other(self, config: Config) -> None:
        """Letting the exception out of the loop would cancel a neighbour's work silently."""
        endpoint = build_agents(orders=RetryingHandler, billing=BillingHandler)

        await endpoint.publish("orders.created", event())

        assert sorted(CALLS) == ["billing", "orders"]


class TestTheSingleAcknowledgement:
    async def test_all_succeeding_acknowledges(self, config: Config) -> None:
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)

        assert await endpoint.publish("orders.created", event()) == {"status": "SUCCESS"}

    async def test_one_retry_wins_over_a_success(self, config: Config) -> None:
        """There is one delivery, so one answer: the only way to retry that agent is to retry all."""
        endpoint = build_agents(orders=RetryingHandler, billing=BillingHandler)

        answer = await endpoint.publish("orders.created", event())

        assert answer["status"] == "RETRY"
        assert answer["reason"] == "try again"

    async def test_a_drop_alongside_a_success_acknowledges(self, config: Config) -> None:
        """One agent finding it undeliverable is a finished outcome, not a failed delivery."""
        endpoint = build_agents(orders=DroppingHandler, billing=BillingHandler)

        answer = await endpoint.publish("orders.created", event())

        assert answer["status"] == "SUCCESS"

    async def test_a_retry_wins_over_a_drop(self, config: Config) -> None:
        endpoint = build_agents(orders=RetryingHandler, billing=DroppingHandler)

        assert (await endpoint.publish("orders.created", event()))["status"] == "RETRY"

    async def test_every_agent_dropping_drops(self, config: Config) -> None:
        endpoint = build_agents(orders=DroppingHandler, billing=DroppingHandler)

        assert (await endpoint.publish("orders.created", event()))["status"] == "DROP"

    async def test_an_event_nobody_handles_still_acknowledges(self, config: Config) -> None:
        endpoint = build_agents()

        assert await endpoint.publish("orders.created", event()) == {"status": "SUCCESS"}


class TestReadinessIsPerAgent:
    async def test_each_agents_client_is_given_its_own_topics(self, config: Config) -> None:
        """The endpoint is shared; the clients are not, and readiness is reported per client."""
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)
        orders_client = DaprClient(namespace="orders")
        billing_client = DaprClient(namespace="billing")
        orders_client.subscribe = AsyncMock()  # type: ignore[method-assign]
        billing_client.subscribe = AsyncMock()  # type: ignore[method-assign]

        await endpoint.on_startup()

        assert sorted(orders_client.subscribe.call_args[0][0]) == ["orders.created"]
        assert sorted(billing_client.subscribe.call_args[0][0]) == ["invoices.raised", "orders.created"]

    async def test_the_clients_are_kept_per_agent(self, config: Config) -> None:
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)
        for namespace in ("orders", "billing"):
            client = DaprClient(namespace=namespace)
            client.subscribe = AsyncMock()  # type: ignore[method-assign]

        await endpoint.on_startup()

        assert sorted(endpoint._clients) == ["billing", "orders"]

    async def test_no_declared_topic_fetches_no_client(self, config: Config) -> None:
        endpoint = build_agents()

        await endpoint.on_startup()

        assert endpoint._clients == {}

    def test_the_endpoint_takes_no_namespace(self, config: Config) -> None:
        """There is one per process, at the root, and that is structural rather than a default."""
        with pytest.raises(TypeError):
            DaprEventing(namespace="orders")  # type: ignore[call-arg]


class TestADegradedAgentIsNotOffered:
    """C4 under a push transport: the sidecar posts whatever the application thinks."""

    @staticmethod
    def _pause(namespace: str) -> DaprClient:
        """Create that agent's client and pause it, as the supervisor would."""
        with namespace_scope(namespace):
            client = DaprClient()
        client._consumption_paused = True
        return client

    async def test_a_paused_agent_is_skipped(self, config: Config, calls: list[str]) -> None:
        endpoint = build_agents(orders=OrderHandler, billing=BillingHandler)
        self._pause("orders")

        await endpoint.publish("orders.created", event())

        assert calls == ["billing"]

    async def test_the_delivery_is_retried_rather_than_acknowledged(self, config: Config) -> None:
        """Acknowledging would consume the event on behalf of an agent that never saw it."""
        endpoint = build_agents(orders=OrderHandler)
        self._pause("orders")

        answer = await endpoint.publish("orders.created", event())

        assert answer["status"] == "RETRY"
        assert "degraded" in answer["reason"]

    async def test_a_healthy_agent_is_unaffected(self, config: Config, calls: list[str]) -> None:
        endpoint = build_agents(orders=OrderHandler)

        answer = await endpoint.publish("orders.created", event())

        assert answer == {"status": "SUCCESS"}
        assert calls == ["orders"]
