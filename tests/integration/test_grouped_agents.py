"""Two agents in one process, on one broker: C1 by observation.

The first *chore* from `docs/plans/2026-09-11-broker-integration-tests.md`, and the one the whole
grouping feature rests on. C1 says an agent's broker-side identity derives from **the agent**, not
from the deployment it happens to be in -- so moving an agent between groups, or hosting it beside
a neighbour, must not change what it subscribes to, what queue group it joins, or what durable it
binds.

The unit tests assert the *names* the framework derives. These assert the *consequence*, which is
a different claim and the one a deployment actually depends on:

- each agent receives only what is published to its own topics, with a neighbour subscribed to the
  broker at the same time;
- the queue group and the durable are the agent's, not the group's -- and are byte-identical to
  what the same agent produces deployed alone, which is what makes a regrouping safe;
- the two agents' consumers are separate objects on the server, so neither can consume the
  other's backlog.

Everything here runs against one NATS and one stream, because that is the deployment being
described: one process, one connection per agent, one stream shared by the group.
"""

import asyncio
import uuid
from typing import Any

import pytest
from nats.js import JetStreamContext

from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent

from .helpers import wait_until


def handler_for(topic: str, seen: list[str]) -> type[EventHandlerBase]:
    """A handler subscribed to one topic, recording the ids it is given."""

    class ScopedHandler(EventHandlerBase):
        async def on_startup(self) -> None:
            pass

        async def on_shutdown(self) -> None:
            pass

        def get_subscribed_topics(self) -> list[str]:
            return [topic]

        async def can_handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> bool:
            return True

        async def handle_event(self, event: GenericCloudEvent, context: dict[str, Any]) -> None:
            seen.append(event.id)
            return None

    return ScopedHandler


def an_event() -> GenericCloudEvent:
    return GenericCloudEvent(id=str(uuid.uuid4()), source="integration-test", type="thing.happened", data={})


class TestEachAgentReceivesOnlyItsOwn:
    """A neighbour is on the same broker, the same stream and the same process."""

    @pytest.fixture
    def two_agents(self, agent_names: tuple[str, str], subject_prefix: str) -> dict[str, Any]:
        """Two agents, each on a topic of its own, sharing everything else."""
        orders, billing = agent_names
        seen: dict[str, list[str]] = {orders: [], billing: []}
        topics = {orders: f"{subject_prefix}.orders.created", billing: f"{subject_prefix}.billing.raised"}
        handlers = {name: handler_for(topics[name], seen[name]) for name in (orders, billing)}
        return {"handlers": handlers, "topics": topics, "seen": seen, "orders": orders, "billing": billing}

    async def test_an_event_reaches_one_agent_and_not_the_other(
        self, nats_group: Any, two_agents: dict[str, Any], jetstream: JetStreamContext
    ) -> None:
        """The claim in its plainest form. Both agents are subscribed, on one connection each, to
        one stream -- and a message on one topic is delivered to exactly one of them."""
        orders, billing = two_agents["orders"], two_agents["billing"]
        event = an_event()

        async with nats_group(two_agents["handlers"]):
            await jetstream.publish(two_agents["topics"][orders], event.model_dump_json().encode())
            await wait_until(
                lambda: bool(two_agents["seen"][orders]),
                timeout=15,
                description=f"agent '{orders}' to receive its own event",
            )
            await asyncio.sleep(1.0)  # long enough for a misrouted delivery to have arrived

        assert two_agents["seen"][orders] == [event.id]
        assert two_agents["seen"][billing] == [], "the neighbour received an event addressed to another agent"

    async def test_each_agent_receives_its_own_when_both_are_published(
        self, nats_group: Any, two_agents: dict[str, Any], jetstream: JetStreamContext
    ) -> None:
        """Both directions at once, so a test cannot pass by one agent simply being idle."""
        orders, billing = two_agents["orders"], two_agents["billing"]
        to_orders, to_billing = an_event(), an_event()

        async with nats_group(two_agents["handlers"]):
            await jetstream.publish(two_agents["topics"][orders], to_orders.model_dump_json().encode())
            await jetstream.publish(two_agents["topics"][billing], to_billing.model_dump_json().encode())

            await wait_until(
                lambda: bool(two_agents["seen"][orders]) and bool(two_agents["seen"][billing]),
                timeout=15,
                description="both agents to receive their own event",
            )
            await asyncio.sleep(1.0)

        assert two_agents["seen"][orders] == [to_orders.id]
        assert two_agents["seen"][billing] == [to_billing.id]


class TestTheBrokerSideIdentityIsTheAgents:
    """What a regrouping must not change."""

    @pytest.fixture
    def one_topic_each(self, agent_names: tuple[str, str], subject_prefix: str) -> dict[str, Any]:
        orders, billing = agent_names
        seen: dict[str, list[str]] = {orders: [], billing: []}
        topic = f"{subject_prefix}.shared.topic"
        return {
            "handlers": {name: handler_for(topic, seen[name]) for name in (orders, billing)},
            "topic": topic,
            "seen": seen,
            "orders": orders,
            "billing": billing,
        }

    async def test_the_queue_group_is_the_agent_not_the_group(self, nats_group: Any, one_topic_each: dict[str, Any]) -> None:
        """`AgentGroup("integration", ...)` is the deployment. Nothing broker-side may carry it,
        or moving an agent to another group would move its queue group with it."""
        orders, billing = one_topic_each["orders"], one_topic_each["billing"]

        async with nats_group(one_topic_each["handlers"]) as clients:
            assert clients[orders].queue_group == orders
            assert clients[billing].queue_group == billing
            assert "integration" not in clients[orders].queue_group

    async def test_two_agents_on_one_topic_get_a_durable_each(
        self, nats_group: Any, one_topic_each: dict[str, Any], jetstream: JetStreamContext, jetstream_stream: str
    ) -> None:
        """The sharpest case: both agents subscribe to the *same* subject. Sharing a durable
        would make them one consumer splitting the messages between them -- each agent seeing
        half its own events, which is the failure P1 and P6 exist to prevent."""
        async with nats_group(one_topic_each["handlers"]):
            consumers = await jetstream.consumers_info(jetstream_stream)

        names = sorted(consumer.name for consumer in consumers)
        assert len(names) == 2, f"two agents on one subject produced {names}"
        assert names[0] != names[1]

    async def test_both_agents_receive_an_event_on_a_subject_they_share(
        self, nats_group: Any, one_topic_each: dict[str, Any], jetstream: JetStreamContext
    ) -> None:
        """The consequence of the durable each: a subject two agents both care about is
        delivered to both, rather than being split between them."""
        orders, billing = one_topic_each["orders"], one_topic_each["billing"]
        event = an_event()

        async with nats_group(one_topic_each["handlers"]):
            await jetstream.publish(one_topic_each["topic"], event.model_dump_json().encode())
            await wait_until(
                lambda: bool(one_topic_each["seen"][orders]) and bool(one_topic_each["seen"][billing]),
                timeout=15,
                description="both agents to receive the shared subject",
            )

        assert one_topic_each["seen"][orders] == [event.id]
        assert one_topic_each["seen"][billing] == [event.id]


class TestAnAgentIsUnchangedByBeingGrouped:
    """The migration claim: the same agent, hosted alone and hosted beside a neighbour, presents
    the same names to the broker. Asserted by running it both ways in one test."""

    async def test_the_queue_group_and_durable_are_byte_identical(
        self, nats_group: Any, agent_names: tuple[str, str], subject_prefix: str, jetstream: JetStreamContext, jetstream_stream: str
    ) -> None:
        """If these differed, regrouping would strand an agent's in-flight backlog on a consumer
        nothing binds to any more -- a migration rather than a deployment change."""
        orders, billing = agent_names
        topic = f"{subject_prefix}.orders.created"

        async with nats_group({orders: handler_for(topic, [])}) as alone:
            alone_group = alone[orders].queue_group
            alone_durables = sorted(consumer.name for consumer in await jetstream.consumers_info(jetstream_stream))

        async with nats_group({orders: handler_for(topic, []), billing: handler_for(f"{subject_prefix}.billing.raised", [])}) as grouped:
            grouped_group = grouped[orders].queue_group
            grouped_durables = sorted(consumer.name for consumer in await jetstream.consumers_info(jetstream_stream))

        assert grouped_group == alone_group
        assert set(alone_durables) <= set(grouped_durables), (
            f"the durable this agent bound alone ({alone_durables}) is not among the ones it binds "
            f"in a group ({grouped_durables}), so its backlog would be stranded by the move"
        )
