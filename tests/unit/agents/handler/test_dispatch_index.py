"""Unit tests for the dispatch index (spec sec. 7.7).

The index is an optimisation with one hard requirement attached: it must not change which
handler processes an event. So most of these compare the indexed behaviour against the
behaviour of a handler set that declares nothing -- which is every handler that exists in this
framework or in any project scaffolded from it.
"""

from pathlib import Path
from typing import Any

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.handler.handler_chain import DispatchIndex, HandlerChain
from blueprint.agents.models.events import GenericCloudEvent

CALLS: list[str] = []
"""Which handlers were asked, in order. Reset by the ``calls`` fixture."""


class RecordingHandler(EventHandlerBase):
    """Records that it was asked, and handles whatever it is asked about."""

    DECLARES: list[str] = []

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    def get_handled_event_types(self) -> list[str]:
        return list(self.DECLARES)

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        CALLS.append(self.name)
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        return {"handled_by": self.name}


class UndeclaredHandler(RecordingHandler):
    """The shape of every handler that exists today: it selects in can_handle_event only."""


class OrderHandler(RecordingHandler):
    DECLARES = ["order.created"]


class InvoiceHandler(RecordingHandler):
    DECLARES = ["invoice.raised", "invoice.paid"]


class PassingHandler(RecordingHandler):
    """Declares an event type, is asked, says yes, and then returns None from handle."""

    DECLARES = ["order.created"]

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        return None


class PatternHandler(RecordingHandler):
    DECLARES = ["order.*"]


class BlankHandler(RecordingHandler):
    DECLARES = ["   "]


@pytest.fixture(autouse=True)
def calls() -> list[str]:
    CALLS.clear()
    return CALLS


@pytest.fixture
def config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text('[development]\napp_name = "indexed"\napp_port = 8000\n')
    loaded = Config(settings_files=[str(settings)], root_path=str(tmp_path))
    Component.configure(loaded)
    return loaded


def event(event_type: str) -> GenericCloudEvent:
    return GenericCloudEvent.model_construct(id="evt-1", type=event_type, source="/tests")


class TestUndeclaredHandlersAreAlwaysCandidates:
    def test_a_handler_that_declares_nothing_is_a_candidate_for_everything(self, config: Config) -> None:
        """The requirement the whole design turns on: an empty declaration is not an empty set."""
        handler = UndeclaredHandler()
        index = DispatchIndex.build((handler,))

        assert index.candidates("anything.at.all") == (handler,)

    def test_it_is_a_candidate_alongside_a_declared_handler(self, config: Config) -> None:
        undeclared, orders = UndeclaredHandler(), OrderHandler()
        index = DispatchIndex.build((undeclared, orders))

        assert index.candidates("order.created") == (undeclared, orders)

    def test_an_undeclared_only_application_indexes_to_nothing(self, config: Config) -> None:
        """Today's every application: no event type is keyed, and everyone is asked."""
        index = DispatchIndex.build((UndeclaredHandler(),))

        assert index.by_type == {}
        assert len(index.wildcard) == 1


class TestDeclarationsNarrowWhoIsAsked:
    def test_a_declared_handler_is_not_a_candidate_for_another_type(self, config: Config) -> None:
        orders, invoices = OrderHandler(), InvoiceHandler()
        index = DispatchIndex.build((orders, invoices))

        assert index.candidates("order.created") == (orders,)

    def test_every_declared_type_is_keyed(self, config: Config) -> None:
        index = DispatchIndex.build((InvoiceHandler(),))

        assert sorted(index.by_type) == ["invoice.paid", "invoice.raised"]

    def test_an_undeclared_type_falls_back_to_the_wildcard_handlers(self, config: Config) -> None:
        undeclared, orders = UndeclaredHandler(), OrderHandler()
        index = DispatchIndex.build((undeclared, orders))

        assert index.candidates("something.else") == (undeclared,)

    def test_an_undeclared_type_with_no_wildcard_handler_has_no_candidates(self, config: Config) -> None:
        index = DispatchIndex.build((OrderHandler(),))

        assert index.candidates("something.else") == ()


class TestOrderIsPreserved:
    def test_candidates_keep_the_order_they_were_given(self, config: Config) -> None:
        """Built by filtering the priority-sorted list, not by concatenating buckets.

        Concatenating would put declared handlers ahead of undeclared ones of equal priority,
        and equal priority is currently resolved by registration order.
        """
        first = UndeclaredHandler()
        first.name = "first"  # two instances of one class would collide on the derived name
        second = OrderHandler()
        third = UndeclaredHandler()
        index = DispatchIndex.build((first, second, third))

        assert index.candidates("order.created") == (first, second, third)

    def test_priority_still_decides(self, config: Config) -> None:
        low, high = OrderHandler(priority=10), UndeclaredHandler(priority=1)
        chain = HandlerChain()

        assert chain._handlers() == (high, low)


class TestDispatchThroughTheIndex:
    async def test_only_the_candidates_are_asked(self, config: Config) -> None:
        OrderHandler()
        InvoiceHandler()
        chain = HandlerChain()

        await chain.process(event("order.created"), {})

        assert CALLS == ["order_handler"]

    async def test_the_undeclared_handler_is_asked_too(self, config: Config) -> None:
        UndeclaredHandler()
        OrderHandler()
        chain = HandlerChain()

        await chain.process(event("order.created"), {})

        assert CALLS == ["undeclared_handler"]  # first candidate returns a result, chain stops

    async def test_a_handler_declaring_nothing_still_receives_an_unknown_type(self, config: Config) -> None:
        UndeclaredHandler()
        OrderHandler()
        chain = HandlerChain()

        result = await chain.process(event("nobody.declared.this"), {})

        assert (CALLS, result) == (["undeclared_handler"], {"handled_by": "undeclared_handler"})

    async def test_the_fallthrough_is_preserved(self, config: Config) -> None:
        """A candidate whose handle returns None still passes the event to the next."""
        PassingHandler(priority=1)
        OrderHandler(priority=2)
        chain = HandlerChain()

        result = await chain.process(event("order.created"), {})

        assert CALLS == ["passing_handler", "order_handler"]
        assert result == {"handled_by": "order_handler"}

    async def test_an_event_no_candidate_wants_returns_none(self, config: Config) -> None:
        OrderHandler()
        chain = HandlerChain()

        assert await chain.process(event("invoice.paid"), {}) is None
        assert CALLS == []


class TestMalformedDeclarations:
    def test_a_pattern_is_refused(self, config: Config) -> None:
        """Matched by equality, so 'order.*' would be a handler that never runs."""
        with pytest.raises(ValueError, match="looks like a pattern"):
            DispatchIndex.build((PatternHandler(),))

    def test_the_refusal_names_the_handler_and_the_declaration(self, config: Config) -> None:
        with pytest.raises(ValueError, match=r"'pattern_handler'.*'order\.\*'"):
            DispatchIndex.build((PatternHandler(),))

    def test_a_blank_declaration_is_refused(self, config: Config) -> None:
        with pytest.raises(ValueError, match="empty event type"):
            DispatchIndex.build((BlankHandler(),))

    async def test_it_fails_at_startup_not_at_a_delivery(self, config: Config) -> None:
        PatternHandler()
        chain = HandlerChain()

        with pytest.raises(ValueError, match="looks like a pattern"):
            await chain.on_startup()


class TestIndexLifecycle:
    async def test_the_index_is_built_at_startup(self, config: Config) -> None:
        OrderHandler()
        chain = HandlerChain()

        await chain.on_startup()

        assert chain._index is not None

    async def test_a_handler_registered_after_startup_is_still_asked(self, config: Config) -> None:
        """Before the index the chain queried the registry per event and picked this up.

        Losing that silently is the failure this design is most careful about, so the index is
        rebuilt when the registered handlers change.
        """
        OrderHandler()
        chain = HandlerChain()
        await chain.on_startup()

        UndeclaredHandler()
        await chain.process(event("late.arrival"), {})

        assert CALLS == ["undeclared_handler"]

    async def test_the_index_is_not_rebuilt_when_nothing_changed(self, config: Config) -> None:
        OrderHandler()
        chain = HandlerChain()
        await chain.on_startup()
        built = chain._index

        await chain.process(event("order.created"), {})

        assert chain._index is built

    async def test_a_chain_used_without_startup_still_indexes(self, config: Config) -> None:
        """The chain is not a registered component, so a caller outside AppBuilder never starts it."""
        OrderHandler()
        chain = HandlerChain()

        await chain.process(event("order.created"), {})

        assert CALLS == ["order_handler"]


class TestPerAgentIndexes:
    async def test_each_agent_indexes_only_its_own_handlers(self, config: Config) -> None:
        with namespace_scope("orders"):
            OrderHandler()
        with namespace_scope("billing"):
            InvoiceHandler()

        orders_chain = HandlerChain(namespace="orders")
        await orders_chain.on_startup()

        assert sorted(orders_chain._index.by_type) == ["order.created"]  # type: ignore[union-attr]

    async def test_one_agents_declaration_does_not_reach_another(self, config: Config) -> None:
        with namespace_scope("orders"):
            OrderHandler()
        with namespace_scope("billing"):
            UndeclaredHandler()

        billing_chain = HandlerChain(namespace="billing")
        await billing_chain.process(event("order.created"), {})

        assert CALLS == ["billing_undeclared_handler"]
