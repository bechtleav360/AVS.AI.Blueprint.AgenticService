"""Binding a handler to an agent runtime (plan phase 7).

The runtime is resolved between ``can_handle`` saying yes and ``handle`` running, and put in the
context the handler is about to be given. That timing is the whole point: it is the only moment
at which the winner is known *and* the answer can still be used.

Three sources, most explicit first -- the handler's own ``get_runtime_name``, the ``runtime_name``
a caller passed to ``process_event``, then the single runtime in the handler's namespace. What is
deliberately *not* here is a failure when several runtimes exist and nothing was declared; see
``TestAmbiguity``.
"""

from pathlib import Path
from typing import Any

import pytest

from blueprint.agents.agent.agent_runtime import AgentRuntime
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope, qualified_component_name
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.handler.handler_chain import RUNTIME_CONTEXT_KEY, RUNTIME_NAME_CONTEXT_KEY, HandlerChain
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.services.eventing.event_processing_service import EventProcessingService

SEEN: list[dict[str, Any]] = []
"""The context each handler was given, so the binding can be inspected after the fact."""


class RecordingHandler(EventHandlerBase):
    """Records the context it was handed, which is where the runtime is bound."""

    RUNTIME: str | None = None

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    def get_runtime_name(self, event: GenericCloudEvent, context: dict[str, Any]) -> str | None:
        return self.RUNTIME

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        SEEN.append(dict(context))
        return {"ok": True}


class UndeclaredHandler(RecordingHandler):
    """The shape of every handler that exists today: it declares no runtime."""


class FastHandler(RecordingHandler):
    RUNTIME = "fast"


class MissingRuntimeHandler(RecordingHandler):
    RUNTIME = "nope"


class PayloadRoutingHandler(RecordingHandler):
    """The case get_runtime_name exists for: the choice depends on the event."""

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> Any:
        SEEN.append(dict(context))
        return {"ok": True}

    def get_runtime_name(self, event: GenericCloudEvent, context: dict[str, Any]) -> str | None:
        return "thorough" if (event.data or {}).get("priority") == "high" else "fast"


@pytest.fixture(autouse=True)
def seen() -> list[dict[str, Any]]:
    SEEN.clear()
    return SEEN


@pytest.fixture
def config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "root-app"\napp_port = 8000\nai_model_provider = "vllm"\n'
        'ai_model_name = "test"\nai_model_api_key = "k"\nai_model_base_url = "http://localhost"\n\n'
        '[development.orders]\napp_name = "orders"\n\n'
        '[development.billing]\napp_name = "billing"\n'
    )
    loaded = Config(settings_files=[str(settings)], root_path=str(tmp_path))
    Component.configure(loaded)
    return loaded


def runtime(name: str, namespace: str = "") -> AgentRuntime:
    """Register an agent runtime under ``name``, in ``namespace``.

    The name is qualified the way ``AppBuilder._register`` qualifies one, because an explicit
    ``name=`` reaches ``Component`` verbatim: two agents called ``planner`` in two namespaces
    would otherwise collide on the one registry key. Constructing the component directly, as
    this helper does, bypasses the builder that normally does the qualifying.
    """
    with namespace_scope(namespace):
        agent = AgentRuntime(model="test", name=qualified_component_name(namespace, name))
    return agent


def event(priority: str | None = None) -> GenericCloudEvent:
    data = {"priority": priority} if priority else {}
    return GenericCloudEvent.model_construct(id="evt-1", type="test.event", source="/tests", data=data)


class TestTheHandlersOwnChoice:
    async def test_a_declared_runtime_is_bound(self, config: Config) -> None:
        fast = runtime("fast")
        runtime("thorough")
        FastHandler()

        await HandlerChain().process(event(), {})

        assert SEEN[0][RUNTIME_NAME_CONTEXT_KEY] == "fast"
        assert SEEN[0][RUNTIME_CONTEXT_KEY] is fast

    async def test_it_is_bound_before_the_handler_runs(self, config: Config) -> None:
        """The handler reads it from the context it is given, not from a later return value."""
        runtime("fast")
        FastHandler()

        await HandlerChain().process(event(), {})

        assert RUNTIME_CONTEXT_KEY in SEEN[0]

    async def test_the_choice_can_depend_on_the_event(self, config: Config) -> None:
        fast, thorough = runtime("fast"), runtime("thorough")
        PayloadRoutingHandler()
        chain = HandlerChain()

        await chain.process(event(priority="high"), {})
        await chain.process(event(priority="low"), {})

        assert [seen[RUNTIME_CONTEXT_KEY] for seen in SEEN] == [thorough, fast]

    async def test_it_wins_over_the_callers_choice(self, config: Config) -> None:
        fast = runtime("fast")
        runtime("thorough")
        FastHandler()

        await HandlerChain().process(event(), {RUNTIME_NAME_CONTEXT_KEY: "thorough"})

        assert SEEN[0][RUNTIME_CONTEXT_KEY] is fast


class TestTheCallersChoice:
    async def test_a_caller_supplied_name_is_honoured(self, config: Config) -> None:
        """The parameter existed and was only logged; this is what makes it mean something."""
        thorough = runtime("thorough")
        runtime("fast")
        UndeclaredHandler()

        await HandlerChain().process(event(), {RUNTIME_NAME_CONTEXT_KEY: "thorough"})

        assert SEEN[0][RUNTIME_CONTEXT_KEY] is thorough

    async def test_process_event_puts_its_argument_where_the_chain_looks(self, config: Config) -> None:
        thorough = runtime("thorough")
        runtime("fast")
        UndeclaredHandler()
        service = EventProcessingService()

        await service.process_event(event(), runtime_name="thorough")

        assert SEEN[0][RUNTIME_CONTEXT_KEY] is thorough

    async def test_passing_nothing_leaves_the_key_absent(self, config: Config) -> None:
        """Absent means "no preference"; None would mean "explicitly no runtime"."""
        UndeclaredHandler()
        service = EventProcessingService()

        await service.process_event(event())

        assert RUNTIME_NAME_CONTEXT_KEY not in SEEN[0]


class TestTheSingleRuntimeFallback:
    async def test_one_runtime_is_bound_without_any_declaration(self, config: Config) -> None:
        """What a single-agent application has in practice, so it needs no declaration."""
        only = runtime("planner")
        UndeclaredHandler()

        await HandlerChain().process(event(), {})

        assert SEEN[0][RUNTIME_CONTEXT_KEY] is only
        assert SEEN[0][RUNTIME_NAME_CONTEXT_KEY] == "planner"

    async def test_no_runtime_at_all_binds_nothing(self, config: Config) -> None:
        """Most applications have no agent; nothing about that is an error."""
        UndeclaredHandler()

        await HandlerChain().process(event(), {})

        assert RUNTIME_CONTEXT_KEY not in SEEN[0]

    async def test_each_agent_gets_its_own_runtime(self, config: Config) -> None:
        """The namespace is named explicitly, so a neighbour's runtime is never reachable."""
        orders_runtime = runtime("planner", namespace="orders")
        runtime("planner", namespace="billing")
        with namespace_scope("orders"):
            UndeclaredHandler()

        await HandlerChain(namespace="orders").process(event(), {})

        assert SEEN[0][RUNTIME_CONTEXT_KEY] is orders_runtime

    async def test_a_neighbours_runtime_does_not_count_towards_the_one(self, config: Config) -> None:
        """Two runtimes in the process but one per agent, so each agent's choice is unambiguous."""
        runtime("planner", namespace="orders")
        billing_runtime = runtime("planner", namespace="billing")
        with namespace_scope("billing"):
            UndeclaredHandler()

        await HandlerChain(namespace="billing").process(event(), {})

        assert SEEN[0][RUNTIME_CONTEXT_KEY] is billing_runtime


class TestAmbiguity:
    async def test_several_runtimes_and_no_declaration_binds_nothing(self, config: Config) -> None:
        """The plan asks for an error here; that would break applications that work today.

        Two agents plus handlers that resolve their own runtime by name is a supported shape,
        and those applications rely on the framework resolving nothing.
        """
        runtime("fast")
        runtime("thorough")
        UndeclaredHandler()

        result = await HandlerChain().process(event(), {})

        assert result == {"ok": True}
        assert RUNTIME_CONTEXT_KEY not in SEEN[0]

    async def test_the_ambiguity_is_reported(self, config: Config, caplog: pytest.LogCaptureFixture) -> None:
        runtime("fast")
        runtime("thorough")
        UndeclaredHandler()

        with caplog.at_level("WARNING", logger="blueprint.agents.handler.handler_chain"):
            await HandlerChain().process(event(), {})

        assert "did not say which agent runtime" in caplog.text
        assert "fast" in caplog.text and "thorough" in caplog.text

    async def test_it_is_reported_once_and_not_per_delivery(self, config: Config, caplog: pytest.LogCaptureFixture) -> None:
        """The condition is a property of the code, so a per-event warning would bury it."""
        runtime("fast")
        runtime("thorough")
        UndeclaredHandler()
        chain = HandlerChain()

        with caplog.at_level("WARNING", logger="blueprint.agents.handler.handler_chain"):
            await chain.process(event(), {})
            await chain.process(event(), {})

        assert caplog.text.count("did not say which agent runtime") == 1


class TestADeclarationThatCannotBeHonoured:
    async def test_an_unknown_runtime_raises(self, config: Config) -> None:
        """A declaration the framework cannot honour is a failure, not something to fall back from."""
        runtime("fast")
        MissingRuntimeHandler()

        with pytest.raises(ValueError, match="asked for agent runtime 'nope'"):
            await HandlerChain().process(event(), {})

    async def test_the_error_names_what_is_registered(self, config: Config) -> None:
        runtime("fast")
        MissingRuntimeHandler()

        with pytest.raises(ValueError, match="registered here: fast"):
            await HandlerChain().process(event(), {})

    async def test_the_error_names_the_handler_and_the_namespace(self, config: Config) -> None:
        with namespace_scope("orders"):
            MissingRuntimeHandler()

        with pytest.raises(ValueError, match=r"'orders_missing_runtime_handler'.*'orders'"):
            await HandlerChain(namespace="orders").process(event(), {})


class TestTheDefaultHook:
    def test_it_returns_none(self, config: Config) -> None:
        """Every handler that exists today inherits this, and nothing about it resolves."""
        handler = UndeclaredHandler()
        assert handler.get_runtime_name(event(), {}) is None
