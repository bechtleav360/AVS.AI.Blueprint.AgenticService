"""Per-agent dispatch, against real components rather than mocks.

What is being tested is that an event delivered for one agent reaches that agent's handlers and
no others, that each agent's chain reads that agent's own configuration, and that an application
which never mentions a namespace is dispatched exactly as it was before any of this existed.

Real ``Config``, real ``Registry``, real ``HandlerChain`` and real handler subclasses on purpose:
the routing is a composition of ``Component.registry``, ``Component.config`` and the registry's
namespace filtering, and a mocked registry would assert the call rather than the outcome.
"""

from pathlib import Path
from typing import Any

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import ROOT_NAMESPACE, namespace_scope
from blueprint.agents.component.registry import DEFAULT_CACHE_NAME
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.handler.handler_chain import HandlerChain
from blueprint.agents.models.config import CacheConfig
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.models.result import ProcessingStatus
from blueprint.agents.services.eventing.event_processing_service import EventProcessingService
from blueprint.agents.services.infrastructure.cache_backend_factory import CacheBackendFactory

CALLS: list[str] = []
"""Which handlers ran, in order. Reset by the ``calls`` fixture."""


class RecordingHandler(EventHandlerBase):
    """A handler written the way a project writes one -- it knows nothing about namespaces."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        CALLS.append(self.name)
        return {"handled_by": self.name}


class OrderHandler(RecordingHandler):
    pass


class BillingHandler(RecordingHandler):
    pass


@pytest.fixture(autouse=True)
def calls() -> list[str]:
    CALLS.clear()
    return CALLS


@pytest.fixture
def two_agent_config(tmp_path: Path) -> Config:
    """A root and two agents, one of which enables deduplication and the other does not.

    A cache is registered as well, and **for ``orders``** rather than at the root, because
    ``orders`` is the agent that opts into deduplication and a chain refuses to resolve that
    policy with nowhere to keep the markers. A root cache would not do: a cache belongs to the
    agent that declared it and no other agent can reach it (spec sec. 8).
    """
    settings = tmp_path / "settings.toml"
    content = """
        [development]
        app_name = "root-app"
        app_port = 8000
        idempotency_enabled = false

        [development.orders]
        app_name = "orders"
        idempotency_enabled = true
        idempotency_ttl = 60

        [development.billing]
        app_name = "billing"
        """
    settings.write_text(content.replace("\n        ", "\n"))
    config = Config(settings_files=[str(settings)], root_path=str(tmp_path))
    Component.configure(config)

    cache = CacheBackendFactory.create(CacheConfig(cache_dir=str(tmp_path / "cache")), namespace="orders")
    registry = Component.shared_registry
    assert registry is not None
    registry.add_cache(DEFAULT_CACHE_NAME, cache, namespace="orders")
    return config


@pytest.fixture
def event() -> GenericCloudEvent:
    return GenericCloudEvent.model_construct(id="evt-1", type="test.event", source="/tests")


def build_two_agents() -> None:
    """Register one handler per agent, the way a registration applied per namespace does."""
    with namespace_scope("orders"):
        OrderHandler()
    with namespace_scope("billing"):
        BillingHandler()


class TestDispatchGoesToOneAgent:
    async def test_only_that_agents_handler_runs(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        build_two_agents()
        service = EventProcessingService()

        await service.process_event(event, namespace="orders")

        assert CALLS == ["orders_order_handler"]

    async def test_the_other_agent_is_reachable_too(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        build_two_agents()
        service = EventProcessingService()

        await service.process_event(event, namespace="billing")

        assert CALLS == ["billing_billing_handler"]

    async def test_a_namespace_with_no_handler_finds_nobody(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        """Not an error: 'no handler' is an outcome the acknowledgement contract already has."""
        build_two_agents()
        service = EventProcessingService()

        result = await service.process_event(event, namespace="shipping")

        assert (result.status, CALLS) == (ProcessingStatus.NO_HANDLER_FOUND, [])

    async def test_the_root_chain_does_not_reach_into_an_agent(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        """The hazard behind naming the namespace explicitly in ``_dispatch``.

        On the root registry an omitted namespace means *every* namespace, so a root dispatch
        would otherwise run both agents' handlers for one delivery.
        """
        build_two_agents()
        service = EventProcessingService()

        result = await service.process_event(event)

        assert (result.status, CALLS) == (ProcessingStatus.NO_HANDLER_FOUND, [])

    async def test_a_root_handler_does_not_run_for_an_agent(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        """No fallback to root handlers: one would otherwise run for every agent in the group."""
        RecordingHandler()
        build_two_agents()
        service = EventProcessingService()

        await service.process_event(event, namespace="orders")

        assert CALLS == ["orders_order_handler"]


class TestSingleAgentApplicationsAreUnchanged:
    async def test_a_root_handler_receives_a_root_dispatch(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        RecordingHandler()
        service = EventProcessingService()

        result = await service.process_event(event)

        assert (result.status, CALLS) == (ProcessingStatus.PROCESSED, ["recording_handler"])

    async def test_every_root_handler_is_offered_the_event(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        """Two handlers at the root are both candidates, which is today's chain behaviour."""
        OrderHandler()
        BillingHandler()
        service = EventProcessingService()

        await service.process_event(event)

        assert len(CALLS) == 1  # the first to return a result stops the chain
        assert CALLS[0] in {"order_handler", "billing_handler"}

    async def test_a_rest_request_reaches_the_root_handler(self, two_agent_config: Config) -> None:
        RecordingHandler()
        service = EventProcessingService()

        result = await service.process_rest_request({"x": 1})

        assert (result.status, CALLS) == (ProcessingStatus.PROCESSED, ["recording_handler"])


class TestChainsPerAgent:
    async def test_one_chain_is_built_per_namespace_with_handlers(self, two_agent_config: Config) -> None:
        build_two_agents()
        service = EventProcessingService()

        await service.on_startup()

        assert sorted(service._handler_chains) == [ROOT_NAMESPACE, "billing", "orders"]

    async def test_each_chain_carries_its_own_namespace(self, two_agent_config: Config) -> None:
        build_two_agents()
        service = EventProcessingService()

        await service.on_startup()

        assert service._handler_chains["orders"].namespace == "orders"

    async def test_each_chain_reads_its_own_agents_configuration(self, two_agent_config: Config) -> None:
        """C5 through the chain: dedup is on for orders and off for billing, from one settings tree."""
        build_two_agents()
        service = EventProcessingService()

        await service.on_startup()

        orders = service._handler_chains["orders"]._policy
        billing = service._handler_chains["billing"]._policy
        assert orders is not None and billing is not None
        assert (orders.enabled, orders.ttl, billing.enabled) == (True, 60, False)

    async def test_a_chain_is_created_on_first_use_for_an_unknown_namespace(
        self, two_agent_config: Config, event: GenericCloudEvent
    ) -> None:
        build_two_agents()
        service = EventProcessingService()
        await service.on_startup()

        await service.process_event(event, namespace="shipping")

        assert service._handler_chains["shipping"].namespace == "shipping"

    async def test_the_same_chain_is_reused_across_deliveries(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        build_two_agents()
        service = EventProcessingService()

        await service.process_event(event, namespace="orders")
        first = service._handler_chains["orders"]
        await service.process_event(event, namespace="orders")

        assert service._handler_chains["orders"] is first

    async def test_an_illegal_namespace_is_refused(self, two_agent_config: Config, event: GenericCloudEvent) -> None:
        service = EventProcessingService()

        with pytest.raises(ValueError, match="legal namespace"):
            await service.process_event(event, namespace="Orders")


class TestHandlerChainNamespace:
    def test_a_chain_defaults_to_the_root(self, two_agent_config: Config) -> None:
        assert HandlerChain().namespace == ROOT_NAMESPACE

    def test_a_chain_takes_the_namespace_it_is_given(self, two_agent_config: Config) -> None:
        assert HandlerChain(namespace="orders").namespace == "orders"

    def test_a_chain_is_not_registered(self, two_agent_config: Config) -> None:
        """It is one agent's dispatcher, not a collaborator anything looks up."""
        HandlerChain(namespace="orders")
        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component_names_by_type(HandlerChain) == []

    def test_a_chain_reads_its_own_agents_configuration(self, two_agent_config: Config) -> None:
        assert HandlerChain(namespace="orders").config.get("app_name") == "orders"
