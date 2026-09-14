"""The barrier between two agents sharing one process.

Grouping puts several agents in one operating-system process, one Python interpreter and one
component registry. The promise that makes that acceptable is that **an agent can reach its own
data and nothing else** -- not a neighbour's component, not a neighbour's cache entry, not a
neighbour's configuration value, not a neighbour's events. The unit of concern is a *value*: an
identifier held by one agent must not be readable from another by any route the framework offers.

Every test here is written the same way, because the property only means something when it is
stated in data rather than in structure: a distinctive value is planted in one agent, and the
other agent is asked for it through every API a component actually has. `namespace_of` and
`agent_scope` say what something *is*; these say what can be *read*, which is the claim.

**Five of these tests fail, on four distinct mechanisms.** They are marked `xfail(strict=True)`
rather than deleted or softened, each naming the mechanism that lets the value through. Strict, so
that closing a hole turns the test red until the marker is removed -- a silently-passing xfail is
how a fix gets made and never noticed. All four are in the changelog's *Open points*:

1. the registry's fallback from a qualified name to a bare one reaches a *neighbour's* key, not
   only the root's;
2. an explicit ``namespace=`` argument wins on a view as well as on the application registry, so
   an agent can address any other by naming it -- which costs two tests, because it opens both
   the component lookup and the cache;
3. a scoped ``get()`` resolves a dotted key against the whole configuration tree;
4. one declaration serving two agents constructs both with the *same* mutable argument object.

None of them is reachable by accident, and none of them requires anything but the framework's own
public API and a neighbour's name -- which an agent knows, because it is in the group.

The root namespace is not a neighbour. It holds what the process genuinely shares -- one transport
connection, one health cache -- so an agent resolving a root component is the design working, and
the tests below distinguish that case rather than forbidding it.
"""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.agent_group import AgentGroup
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.services.service_base import ServiceBase

ORDERS_RECORD = "ORDERS-RECORD-4242"
"""Planted in ``orders``. Every assertion below is some form of "billing cannot read this"."""

BILLING_RECORD = "BILLING-RECORD-9999"


class Ledger(ServiceBase):
    """One class, declared by both agents -- the shape a shared library component takes.

    ``holdings`` defaults to ``None`` and is filled per instance, so that any sharing observed
    between two agents comes from the framework rather than from a mutable default argument.
    """

    def __init__(self, holdings: list[str] | None = None) -> None:
        super().__init__()
        self.holdings = holdings
        self.record_id: str | None = None

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    with patch(
        "blueprint.agents.component.registry.CorrelationContextProvider.get_correlation_context",
        return_value=MagicMock(),
    ):
        yield
    Component.reset_shared_state()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A process with shared infrastructure and one private value per agent."""
    settings = tmp_path / "settings.toml"
    settings.write_text(
        "[default]\n"
        'app_name = "the-process"\n'
        'app_environment = "development"\n'
        "app_port = 8000\n"
        'model_provider = "openai"\n'
        'model_api_key = "not-a-real-key"\n'
        'nats_url = "nats://shared:4222"\n\n'
        f'[default.orders]\nrecord_id = "{ORDERS_RECORD}"\n\n'
        f'[default.billing]\nrecord_id = "{BILLING_RECORD}"\n\n'
        f'[default.cache]\ncache_dir = "{(tmp_path / "cache").as_posix()}"\n',
        encoding="utf-8",
    )
    # Deliberately not Component.configure()'d here: AppBuilder.build() does that during
    # assembly, and it refuses a second call.
    return Config(settings_files=["settings.toml"], root_path=str(tmp_path))


@pytest.fixture
def two_agents(config: Config) -> dict[str, Ledger]:
    """Two agents in one process, each with a ledger carrying its own record.

    Assembled through ``AgentGroup`` rather than constructed by hand, because the barrier under
    test is the one a real group produces -- the ambient namespace, the qualified registry keys
    and the scoped configuration views all come from assembly.
    """
    AgentGroup(
        "finance",
        {
            "orders": AppBuilder().with_service(Ledger).with_cache(),
            "billing": AppBuilder().with_service(Ledger).with_cache(),
        },
    ).assemble(config)

    registry = Component.shared_registry
    assert registry is not None
    ledgers = {"orders": registry.get_component("orders_ledger"), "billing": registry.get_component("billing_ledger")}
    ledgers["orders"].record_id = ORDERS_RECORD
    ledgers["billing"].record_id = BILLING_RECORD
    return ledgers


class TestAnAgentSeesItsOwnComponents:
    """The barrier holds for every lookup a component makes without naming a namespace."""

    def test_the_two_agents_are_separate_instances(self, two_agents: dict[str, Ledger]) -> None:
        """One declared class, two agents: two objects. A singleton here would share everything
        at once, so it is the first thing to rule out."""
        assert two_agents["orders"] is not two_agents["billing"]

    def test_a_lookup_by_bare_name_finds_this_agents_own(self, two_agents: dict[str, Ledger]) -> None:
        """How a component actually resolves a collaborator: the name it declared, no namespace.

        Both agents ask for ``ledger`` and each gets its own -- which is the whole ambient
        mechanism, seen from the inside.
        """
        assert two_agents["billing"].registry.get_component("ledger").record_id == BILLING_RECORD
        assert two_agents["orders"].registry.get_component("ledger").record_id == ORDERS_RECORD

    def test_a_lookup_by_class_finds_only_this_agents_own(self, two_agents: dict[str, Ledger]) -> None:
        """The other resolution style, and the one where a neighbour would be easiest to reach:
        both agents' ledgers are instances of the same class, in one registry."""
        found = two_agents["billing"].registry.get_components_by_type(Ledger)

        assert [ledger.record_id for ledger in found] == [BILLING_RECORD]

    def test_listing_names_does_not_name_the_neighbour(self, two_agents: dict[str, Ledger]) -> None:
        """Enumeration is a read too. A component that can list its neighbour's registry keys can
        then ask for them by name, and the key itself may say what the neighbour is for."""
        names = two_agents["billing"].registry.get_component_names_by_type(Ledger)

        assert names == ["billing_ledger"]

    def test_the_shared_root_is_not_a_neighbour(self, config: Config, two_agents: dict[str, Ledger]) -> None:
        """The fallback that must keep working: what the process genuinely shares is resolvable
        from inside an agent, and that is not a hole -- it is what the root namespace is."""
        with namespace_scope(""):
            shared = Ledger()
            shared.name = "shared_ledger"

        assert two_agents["billing"].registry.get_component("shared_ledger") is shared


class TestAnAgentCannotReachANeighboursComponents:
    """Named routes to another agent's objects."""

    def test_a_neighbours_qualified_name_is_not_a_key_this_agent_can_use(self, two_agents: dict[str, Ledger]) -> None:
        """The registry keys are derivable: an agent knows its neighbours' names from the group,
        and the qualifier is a documented ``<namespace>_<name>``. So this was not a guess.

        It reads as *absent*, not refused. A refusal naming the agent would confirm the
        neighbour exists, which is the same disclosure in a smaller size.
        """
        with pytest.raises(ValueError, match="does not exist in namespace 'billing' or at the root"):
            two_agents["billing"].registry.get_component("orders_ledger")

    def test_an_agent_can_still_use_its_own_qualified_name(self, two_agents: dict[str, Ledger]) -> None:
        """The documented behaviour the ownership check must not cost: a caller already holding
        the qualified name resolves it, because qualifying it twice misses and the bare lookup
        then finds a component this agent owns."""
        assert two_agents["orders"].registry.get_component("orders_ledger").record_id == ORDERS_RECORD

    def test_naming_a_neighbours_namespace_is_refused(self, two_agents: dict[str, Ledger]) -> None:
        """Refused rather than answered absent, unlike the fallback above: naming another agent
        is a decision, not a near miss, and a silent ``None`` would read as "that agent has
        nothing registered" -- which is itself a claim about the neighbour."""
        with pytest.raises(RuntimeError, match="neighbour's belong to that agent alone"):
            two_agents["billing"].registry.get_component("ledger", namespace="orders")

    def test_an_agent_may_still_name_its_own_namespace(self, two_agents: dict[str, Ledger]) -> None:
        """What the refusal must not cost: every framework component that passes a namespace
        passes ``self.namespace``, so this is the call the framework itself makes."""
        found = two_agents["billing"].registry.get_component("ledger", namespace="billing")

        assert found.record_id == BILLING_RECORD

    def test_an_agent_may_still_name_the_root(self, two_agents: dict[str, Ledger]) -> None:
        """The root is shared infrastructure, and reaching it explicitly is not a cross-agent
        read -- a view can already reach it by omitting the argument entirely."""
        with namespace_scope(""):
            shared = Ledger()
            shared.name = "shared_ledger"

        assert two_agents["billing"].registry.get_component("shared_ledger", namespace="") is shared


class TestAnAgentCannotReadANeighboursCache:
    """The cache is where an agent's data actually accumulates, so it is the barrier that matters
    most: a component instance holds what is in flight, the cache holds what was kept."""

    @pytest.fixture
    def stored(self, two_agents: dict[str, Ledger]) -> str:
        """A record written into the orders cache, under a key billing also uses."""
        registry = Component.shared_registry
        assert registry is not None
        registry.get_cache("default", namespace="orders").set("record", {"id": ORDERS_RECORD}, namespace="data")
        return "record"

    def test_the_same_key_in_this_agents_cache_is_empty(self, two_agents: dict[str, Ledger], stored: str) -> None:
        """Two agents declaring one cache name get separate stores, so the shared key is the
        sharpest form of the question: same name, same key, different data."""
        billing_cache = two_agents["billing"].registry.get_cache("default")

        assert billing_cache.get(stored, namespace="data") is None

    def test_every_cache_in_the_process_cannot_be_listed_from_inside_an_agent(self, two_agents: dict[str, Ledger]) -> None:
        """C6: ``cache_entries()`` is the one cross-agent view, and a view refuses it outright."""
        with pytest.raises(RuntimeError, match="every cache"):
            two_agents["billing"].registry.cache_entries()

    def test_naming_a_neighbours_namespace_does_not_open_its_cache(self, two_agents: dict[str, Ledger], stored: str) -> None:
        """The same refusal as for components, on the store that actually holds the records.

        ``_cache_owner`` carries its own copy of the check rather than sharing one, because the
        two resolvers mean different things by an omitted argument -- for a cache it means *this
        agent*, never *every agent*, since no cache belongs to all of them.
        """
        with pytest.raises(RuntimeError, match="no agent reads another's"):
            two_agents["billing"].registry.get_cache("default", namespace="orders")


class TestAnAgentCannotReadANeighboursConfiguration:
    """Configuration is one loaded tree with a view per agent, so the tree is the shared surface."""

    def test_a_plain_key_resolves_to_this_agents_value(self, config: Config) -> None:
        assert config.for_namespace("billing").get("record_id") == BILLING_RECORD

    def test_shared_infrastructure_still_resolves(self, config: Config) -> None:
        """The barrier is around an agent's own keys, not around the process's."""
        assert config.for_namespace("billing").get("nats_url") == "nats://shared:4222"

    def test_a_view_cannot_hand_out_a_neighbours_view(self, config: Config) -> None:
        """The obvious route, and the one that is closed: a view is not a loader."""
        with pytest.raises(RuntimeError, match="not from another"):
            config.for_namespace("billing").for_namespace("orders")

    def test_a_dotted_key_cannot_walk_into_a_neighbours_section(self, config: Config) -> None:
        """An agent's section is ``[default.<agent>]``, so its keys are ``<agent>.<key>`` to
        anyone who can resolve a dotted name. The scope used to prefix a key without confining
        it."""
        with pytest.raises(ValueError, match="outside this agent"):
            config.for_namespace("billing").get("orders.record_id")

    def test_the_frameworks_own_nested_sections_still_resolve(self, config: Config) -> None:
        """An allowlist, so what the process genuinely shares keeps working -- and this is the
        case that would have been broken by a denylist of agent names."""
        assert config.for_namespace("billing").get("cache.cache_dir") is not None

    def test_the_loader_is_unrestricted(self, config: Config) -> None:
        """Only a *view* is confined. The application owns its whole tree, and `build()` and the
        environment endpoint read across agents by design."""
        assert config.get("orders.record_id") == ORDERS_RECORD

    def test_the_escape_hatch_is_the_one_way_through_and_it_announces_itself(
        self, config: Config, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``settings`` deliberately returns the unscoped tree; it is audited, not forbidden.

        Recorded here rather than only in the config tests because it belongs in the account of
        what the barrier does *not* stop: an agent that reaches for it can read anything, and all
        that stands in the way is a WARNING naming the agent.
        """
        with caplog.at_level("WARNING"):
            reached = config.for_namespace("billing").settings.get("orders.record_id")

        assert reached == ORDERS_RECORD
        assert "billing" in caplog.text and "not scoped to it" in caplog.text


class TestOneDeclarationDoesNotBecomeASharedObject:
    """The property a group rests on -- one declaration, replayed per agent -- was also the way an
    object could end up belonging to two agents at once.

    ``**`` copies the recorded mapping and not its values, so both agents were constructed with
    the very same list. It is the only one of the four routes that needs no lookup: the object
    arrives in both constructors.
    """

    def test_a_mutable_argument_shared_by_two_agents_is_refused(self, config: Config) -> None:
        declaration = AppBuilder().with_service(Ledger, holdings=[])

        with pytest.raises(ValueError, match="written by one agent is read by the others"):
            AgentGroup("finance", {"orders": declaration, "billing": declaration}).assemble(config)

    def test_the_refusal_names_the_agents_the_argument_and_the_way_out(self, config: Config) -> None:
        """It arrives at assembly, so the message is the only thing the author has to work from."""
        declaration = AppBuilder().with_service(Ledger, holdings=[])

        with pytest.raises(ValueError) as refusal:
            AgentGroup("finance", {"orders": declaration, "billing": declaration}).assemble(config)

        message = str(refusal.value)
        assert "'orders'" in message and "'billing'" in message
        assert "'holdings'" in message and "list" in message
        assert "factory" in message

    def test_a_factory_gives_each_agent_its_own(self, config: Config) -> None:
        """The way out, and the reason no new API was needed: a declaration's target may be a
        zero-argument factory, which is called once per agent."""
        declaration = AppBuilder().with_service(lambda: Ledger(holdings=[]))
        AgentGroup("finance", {"orders": declaration, "billing": declaration}).assemble(config)

        registry = Component.shared_registry
        assert registry is not None
        orders = registry.get_component("orders_ledger")
        billing = registry.get_component("billing_ledger")

        orders.holdings.append(ORDERS_RECORD)
        assert billing.holdings == []

    def test_an_immutable_argument_is_shared_as_it_is(self, config: Config) -> None:
        """Code and unchangeable values are not a channel: two agents already share the declared
        *class*, which is what a declaration is."""
        declaration = AppBuilder().with_service(Ledger, holdings=("read-only",))
        AgentGroup("finance", {"orders": declaration, "billing": declaration}).assemble(config)

        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("orders_ledger").holdings == ("read-only",)

    def test_one_agent_may_carry_whatever_it_likes(self, config: Config) -> None:
        """Only a declaration used by more than one agent is checked -- there is nobody to share
        it with otherwise, and a standalone project must not be punished for the group's rule."""
        AgentGroup("finance", {"orders": AppBuilder().with_service(Ledger, holdings=[])}).assemble(config)

        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("orders_ledger").holdings == []


class TestTheProcessLevelResourcesAreStillPerAgent:
    """Not data, but channels through which data would flow."""

    def test_each_agent_gets_its_own_thread_pool(self, two_agents: dict[str, Ledger]) -> None:
        """A shared pool is a shared queue: one agent's work would be observable in another's
        latency, and a task submitted by one would run beside a task submitted by the other."""
        registry = Component.shared_registry
        assert registry is not None

        assert registry.get_or_create_executor("orders") is not registry.get_or_create_executor("billing")

    def test_each_agent_gets_its_own_cache_store(self, two_agents: dict[str, Ledger]) -> None:
        """Separate objects, which is what makes the key-level isolation above true rather than
        incidental."""
        registry = Component.shared_registry
        assert registry is not None

        assert registry.get_cache("default", namespace="orders") is not registry.get_cache("default", namespace="billing")


class TestAnEventReachesOnlyItsOwnAgent:
    """The live path: a delivery into one agent must not be offered to another agent's handlers."""

    def test_a_handler_chain_answers_for_one_agent(self, two_agents: dict[str, Ledger]) -> None:
        """Each agent's chain is built for its namespace, so the handler set is the agent's own.

        Asserted through the registry rather than by dispatching, because the selection that
        matters happens when the chain is assembled: a handler that is never in the chain can
        never be offered the event.
        """
        registry = Component.shared_registry
        assert registry is not None

        for agent in ("orders", "billing"):
            handlers = registry.get_event_handler(namespace=agent)
            assert all(handler.namespace == agent for handler in handlers), (agent, handlers)
