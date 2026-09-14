"""Guards for the design rules in ``AGENTS.md``, one section per rule.

Prose has already failed once here: ``CLAUDE.md`` cited ``AGENTS.md`` for months while no such
file existed, and nothing noticed. A rule that lives only as a paragraph is a rule the next
feature can break without anyone seeing it, so every rule that can be checked mechanically is
checked here -- and **every failure message names the rule it enforces**, because someone who
hits one of these has not made an ordinary mistake in a test, they have crossed a design decision
and need to read the decision.

What is guarded, in the order ``AGENTS.md`` states the rules:

- *Collect, then wire* -- :class:`TestCollectThenWire`
- *One declaration surface* -- :class:`TestOneDeclarationSurface`
- *A lookup never falls back across agents* -- :class:`TestNoLookupFallsBackAcrossAgents`
- *A component never learns it is in a group* -- :class:`TestNothingEnumeratesTheProcess`
- *A name that crosses the process boundary is validated, never repaired* --
  :class:`TestNamesAreValidatedNeverRepaired`
- *There is no public read path to the unscoped loader* -- :class:`TestNoPublicPathToTheLoader`
- *Logging is configured by the application* -- :class:`TestLoggingIsConfiguredByTheApplication`
- *No diagnostics via print* -- :class:`TestNoDiagnosticsViaPrint`
- *A reference points at a file that exists* -- :class:`TestEveryReferenceResolves`

The last one is what makes the rest durable: a rule recorded in a document nobody can reach is
back to being a paragraph.

Rules that are deliberately **not** guarded here, so that their absence is not read as an
oversight: *a builder is single-use*, *group policy belongs to the collector*, *an empty
declaration means everything* and *a key whose absence changes behaviour is required* are
behaviours with their own suites (``app_builder/test_app_builder.py``, ``test_agent_group.py``,
``handler/``, ``config/``), and asserting them again here would give one rule two homes. *Isolation
is structural where it can be*, *probe against real objects* and *the spec wins on precedence, not
on correctness* cannot be checked by a machine at all.
"""

import ast
import re
from collections.abc import Callable, Generator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from blueprint.agents.agent.agent_builder import AgentBuilder
from blueprint.agents.agent_group import AgentGroup
from blueprint.agents.app_builder import AppBuilder, Declaration
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope, validate_namespace
from blueprint.agents.component.registry import Registry
from blueprint.agents.config import Config
from blueprint.agents.group_config import GroupConfig, GroupConfigError
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.io.api.actuators.health.health_base import HealthCheckerBase
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase
from blueprint.agents.models.api import ComponentHealth
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.services.infrastructure.cache_backend_factory import CacheBackendFactory
from blueprint.agents.services.infrastructure.cache_service import CacheService
from blueprint.agents.services.service_base import ServiceBase

REPO_ROOT = Path(__file__).resolve().parents[3]
"""The repository root, for the guards that read the tree rather than import it."""

FRAMEWORK = REPO_ROOT / "src" / "blueprint" / "agents"
"""The framework package: library code, which is where the rules about library code bind."""


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    """Leave no shared configuration or registry behind, and need no correlation context.

    ``Component`` holds the configuration and the registry as class state, so a guard that
    configures one would otherwise decide what the next one sees. Reset before as well as after,
    because these guards assert on the *absence* of configuration.
    """
    Component.reset_shared_state()
    with patch(
        "blueprint.agents.component.registry.CorrelationContextProvider.get_correlation_context",
        return_value=MagicMock(),
    ):
        yield
    Component.reset_shared_state()


# ----------------------------------------------------------------------------------------------
# Stubs: concrete and minimal, so that every guard below calls a real builder with a real class.
# ----------------------------------------------------------------------------------------------


class StubHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> None:
        return None


class StubService(ServiceBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class StubApi(RestApiBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class StubScheduler(SchedulerBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class StubChecker(HealthCheckerBase):
    async def health_check(self) -> ComponentHealth:
        return ComponentHealth(status="healthy", message="ok")


class StubResult(BaseModel):
    answer: str


SampleCall = tuple[tuple[Any, ...], dict[str, Any]]

APP_BUILDER_CALLS: dict[str, SampleCall] = {
    "with_handler": ((StubHandler,), {"name": "a_handler"}),
    "with_service": ((StubService,), {"name": "a_service"}),
    "with_agent": ((AgentBuilder(runtime_name="a_runtime"),), {}),
    "with_scheduler": ((StubScheduler,), {"name": "a_scheduler"}),
    "with_rest_api": ((StubApi,), {"name": "an_api"}),
    "with_cache": ((), {"name": "a_cache"}),
    "with_health_checker": (("a_check", StubChecker()), {}),
}
"""One call per ``AppBuilder`` declaration method, as a project would write it.

Keyword arguments are given where the method takes a name, because a name is the part replay is
most able to lose: ``with_health_checker`` takes it positionally and every other method takes it
as a keyword, and that irregularity lives in exactly one branch of ``Declaration.replay``.
"""

AGENT_BUILDER_CALLS: dict[str, SampleCall] = {
    "with_model_from_config": ((), {}),
    "with_system_prompt": (("a_prompt",), {}),
    "with_tools": (([],), {}),
    "with_tool": (("a_tool", lambda: None), {}),
    "with_result_type": ((StubResult,), {}),
    "with_deps_type": ((dict,), {}),
    "with_metrics": ((), {}),
}
"""The same for ``AgentBuilder``, which records fields rather than ``Declaration`` objects.

*Collect, then wire* binds it just as hard: ``with_model_from_config`` is the method that used to
read the configuration while accumulating, and that one read is what forced an agent to be built
before its namespace existed.
"""

BUILDERS: dict[str, tuple[Callable[[], Any], dict[str, SampleCall]]] = {
    "AppBuilder": (AppBuilder, APP_BUILDER_CALLS),
    "AgentBuilder": (lambda: AgentBuilder(runtime_name="a_runtime"), AGENT_BUILDER_CALLS),
}
"""Every declaration surface in the framework, with the calls that exercise it."""


def declaration_methods(builder_class: Any) -> list[str]:
    """Every public declaration method on a builder, discovered rather than listed.

    Discovered, so that a method added without a sample call fails this file instead of being
    quietly untested. The ``with_`` prefix is what makes a method a declaration: ``host_agent``
    records no ``Declaration`` -- it states a fact about the process -- and is not one of these.
    """
    return sorted(name for name in dir(builder_class) if name.startswith("with_"))


def surfaces() -> Iterator[tuple[str, str]]:
    """Every ``(builder, method)`` pair the reflective guards run over."""
    for builder_name, (_factory, calls) in BUILDERS.items():
        for method in sorted(calls):
            yield builder_name, method


def record(builder_name: str, method: str) -> tuple[Any, Any]:
    """Make a fresh builder, record one declaration on it from the sample call, and return both."""
    factory, calls = BUILDERS[builder_name]
    builder = factory()
    arguments, keywords = calls[method]
    return builder, getattr(builder, method)(*arguments, **keywords)


def registry_contents() -> dict[str, object]:
    """Every component in the shared registry, or nothing when there is not even a registry yet.

    Read through ``_components`` because there is no public "list everything" method, and there
    should not be: an agent that can enumerate the process can be written to depend on it.
    """
    registry = Component.shared_registry
    return dict(registry._components) if registry is not None else {}


class TestCollectThenWire:
    """**Collect, then wire.** A declaration API records; nothing is constructed until ``build()``.

    *Failure it prevents:* a component constructed while declarations are still being collected
    exists before any namespace does, so it belongs to the root for ever -- which is what forced
    a second builder class to exist for three phases.
    """

    @pytest.mark.parametrize(("builder_name", "method"), list(surfaces()))
    def test_recording_a_declaration_constructs_nothing(self, builder_name: str, method: str) -> None:
        before = registry_contents()

        record(builder_name, method)

        assert registry_contents() == before, (
            f"{builder_name}.{method}() put something in the registry while declarations were still being collected. "
            "Collect, then wire: a component built during accumulation exists before any namespace does and belongs "
            "to the root for ever. Record the call, and construct it in build()."
        )

    @pytest.mark.parametrize(("builder_name", "method"), list(surfaces()))
    def test_recording_a_declaration_needs_no_configuration(self, builder_name: str, method: str) -> None:
        """No configuration is linked here at all, and every declaration must still record.

        The sharper half of the rule: a ``with_*`` that reads a key cannot run before the
        configuration exists, and the configuration does not exist until ``build()`` is handed
        one. ``with_model_from_config`` used to read here, and that is why an agent had to be
        built during accumulation.
        """
        assert not Component.has_config()

        record(builder_name, method)

        assert not Component.has_config(), (
            f"{builder_name}.{method}() linked a configuration while recording. Configuration is injected at "
            "build(), not while declarations are collected."
        )

    @pytest.mark.parametrize(("builder_name", "method"), list(surfaces()))
    def test_a_declaration_returns_the_builder(self, builder_name: str, method: str) -> None:
        """The fluent contract: a project chains these, so anything else breaks its ``main.py``."""
        builder, returned = record(builder_name, method)

        assert returned is builder, f"{builder_name}.{method}() must return the builder, so that declarations chain."


class TestOneDeclarationSurface:
    """**One declaration surface.** Adding a capability is one edit: a ``with_*`` on ``AppBuilder``.

    A group still has to move a recorded call from one builder to another, and
    ``Declaration.replay`` does that by resolving ``with_<kind>`` with ``getattr``. So there are
    exactly two ways for the recorder and the API to part company:

    - a ``with_*`` records a ``kind`` that no method answers to, and replay dies with an
      ``AttributeError`` at assembly -- in a group, never standalone;
    - a ``with_*`` whose replayed arguments do not reproduce the call, so an agent is assembled
      from a declaration that says something slightly different from what its ``main.py`` said.

    Neither is visible in a single-agent application, and both would be found in production by
    somebody grouping two agents.

    *Failure it prevents:* four places to edit, three of which fail **silently** -- the capability
    is simply absent from that deployment shape, and only in the one nobody tested.
    """

    def test_the_sample_calls_name_every_declaration_method(self) -> None:
        missing = set(declaration_methods(AppBuilder)) - set(APP_BUILDER_CALLS)
        assert not missing, (
            f"{', '.join(sorted(missing))} is a declaration method with no sample call in this file. Add one: the "
            "list is what proves a new with_* was checked against the group's replay, which is the only place a "
            "recorder and its API can drift apart."
        )

    def test_the_sample_calls_name_nothing_that_is_gone(self) -> None:
        extra = set(APP_BUILDER_CALLS) - set(declaration_methods(AppBuilder))
        assert not extra, f"{', '.join(sorted(extra))} no longer exists on AppBuilder; remove the sample call."

    def test_the_agent_sample_calls_name_every_declaration_method(self) -> None:
        missing = set(declaration_methods(AgentBuilder)) - set(AGENT_BUILDER_CALLS)
        assert not missing, (
            f"{', '.join(sorted(missing))} is an AgentBuilder declaration method with no sample call in this file. "
            "Add one: collect-then-wire is asserted reflectively, so an unlisted method is an unchecked one."
        )

    def test_the_agent_sample_calls_name_nothing_that_is_gone(self) -> None:
        extra = set(AGENT_BUILDER_CALLS) - set(declaration_methods(AgentBuilder))
        assert not extra, f"{', '.join(sorted(extra))} no longer exists on AgentBuilder; remove the sample call."

    @pytest.mark.parametrize("method", sorted(APP_BUILDER_CALLS))
    def test_the_call_records_exactly_one_declaration(self, method: str) -> None:
        builder, _ = record("AppBuilder", method)

        assert len(builder.declarations) == 1

    @pytest.mark.parametrize("method", sorted(APP_BUILDER_CALLS))
    def test_the_recorded_kind_has_a_method_to_replay_onto(self, method: str) -> None:
        """``Declaration.replay`` resolves ``with_<kind>`` with getattr, and this is that contract."""
        builder, _ = record("AppBuilder", method)

        for declaration in builder.declarations:
            assert hasattr(AppBuilder, f"with_{declaration.kind}"), (
                f"{method}() records kind '{declaration.kind}', but there is no with_{declaration.kind}() for "
                "Declaration.replay to call. A group would fail at assembly with an AttributeError while the same "
                "declaration went on working standalone."
            )

    @pytest.mark.parametrize("method", sorted(APP_BUILDER_CALLS))
    def test_replay_reproduces_the_declaration(self, method: str) -> None:
        """What a group does to move an agent's calls onto the root builder, and it must be lossless."""
        source, _ = record("AppBuilder", method)

        target = AppBuilder()
        for declaration in source.declarations:
            declaration.replay(target)

        assert target.declarations == source.declarations, (
            f"replaying {method}() onto another builder did not reproduce the declaration. A grouped agent would "
            "then be assembled from something other than what its main.py declared."
        )

    @pytest.mark.parametrize("method", sorted(APP_BUILDER_CALLS))
    def test_replay_takes_the_namespace_from_the_scope_it_runs_in(self, method: str) -> None:
        """The ambient mechanism: no namespace is passed, and none appears in any signature."""
        source, _ = record("AppBuilder", method)

        target = AppBuilder()
        with namespace_scope("orders"):
            for declaration in source.declarations:
                declaration.replay(target)

        assert [entry.namespace for entry in target.declarations] == ["orders"]
        assert [entry.namespace for entry in source.declarations] == [""]

    def test_a_replayed_checker_keeps_its_positional_name(self) -> None:
        """``with_health_checker(name, checker)`` is the one method whose name is positional."""
        checker = StubChecker()
        source = AppBuilder().with_health_checker("db", checker)

        target = AppBuilder()
        for declaration in source.declarations:
            declaration.replay(target)

        recorded = target.declarations[0]
        assert (recorded.name, recorded.target) == ("db", checker)

    def test_a_replayed_declaration_keeps_its_name_override(self) -> None:
        source = AppBuilder().with_service(StubService, name="planner")

        target = AppBuilder()
        for declaration in source.declarations:
            declaration.replay(target)

        assert target.declarations[0].name == "planner"

    def test_a_replayed_declaration_keeps_its_constructor_arguments(self) -> None:
        source = AppBuilder().with_cache(True, False, name="sessions")

        target = AppBuilder()
        for declaration in source.declarations:
            declaration.replay(target)

        assert target.declarations[0] == Declaration(
            kind="cache", target=None, name="sessions", namespace="", kwargs={"enable_locking": False}
        )


# ----------------------------------------------------------------------------------------------
# Isolation: what one agent can reach, and what it must not.
# ----------------------------------------------------------------------------------------------


@pytest.fixture
def registry() -> Registry:
    """The application's own registry -- the real one, not a mock.

    A mock registry hides resolution bugs by construction, and resolution is the whole subject
    of the guards that use it.
    """
    return Registry(Component)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A real configuration with a root and two agents, loaded from a real settings file."""
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_environment = "development"\napp_name = "the-process"\napp_port = 8000\n'
        'model_name = "root-model"\n\n'
        '[development.orders]\nmodel_name = "orders-model"\n\n'
        '[development.billing]\nmodel_name = "billing-model"\n'
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


class TestNoLookupFallsBackAcrossAgents:
    """**A lookup never falls back across agents.** Caches do not resolve outside the declaring agent.

    *Failure it prevents:* two agents that both asked for ``sessions`` silently share one store,
    and only in production -- a single-agent test suite cannot see it, because there is no
    neighbour to collide with.
    """

    def test_two_agents_declaring_one_name_get_two_stores(self, registry: Registry) -> None:
        orders_cache = MagicMock(spec=CacheService)
        billing_cache = MagicMock(spec=CacheService)

        registry.add_cache("sessions", orders_cache, namespace="orders")
        registry.add_cache("sessions", billing_cache, namespace="billing")

        assert registry.get_cache("sessions", namespace="orders") is orders_cache
        assert registry.get_cache("sessions", namespace="billing") is billing_cache

    def test_an_agent_cannot_reach_a_neighbours_cache(self, registry: Registry) -> None:
        registry.add_cache("sessions", MagicMock(spec=CacheService), namespace="billing")

        with pytest.raises(ValueError, match="No cache registered as 'sessions' for agent 'orders'"):
            registry.for_namespace("orders").get_cache("sessions")

    def test_an_unknown_name_is_an_error_not_the_default_cache(self, registry: Registry) -> None:
        """The second fallback that does not exist: an unknown name never becomes the default."""
        registry.add_cache("default", MagicMock(spec=CacheService), namespace="orders")

        with pytest.raises(ValueError, match="No cache registered as 'sessions'"):
            registry.for_namespace("orders").get_cache("sessions")

    def test_an_agent_cannot_fall_back_to_the_roots_cache(self, registry: Registry) -> None:
        """Components resolve namespace-then-root; caches deliberately do not."""
        registry.add_cache("sessions", MagicMock(spec=CacheService))

        with pytest.raises(ValueError, match="No cache registered as 'sessions' for agent 'orders'"):
            registry.for_namespace("orders").get_cache("sessions")


class TestNothingEnumeratesTheProcess:
    """**A component never learns it is in a group.** The namespace is ambient and not enumerable.

    *Failure it prevents:* an agent that can read its neighbours can be written to depend on
    them, and regrouping then breaks it in production.
    """

    def test_a_component_takes_its_namespace_from_the_scope_in_force(self) -> None:
        """The ambient mechanism, and the reason no project component has a namespace parameter."""
        Component.init_registry(Registry(Component))

        with namespace_scope("orders"):
            service = StubService()

        assert service.namespace == "orders"

    def test_no_agent_can_enumerate_the_namespaces_in_the_process(self) -> None:
        for subject in (Registry, Component, Config):
            assert not hasattr(subject, "get_known_namespaces"), (
                f"{subject.__name__}.get_known_namespaces exists. Nothing a component can reach may enumerate the "
                "process: an agent that can list its neighbours can be written to depend on them. One endpoint per "
                "agent needs no such list, and assembly reads the group from the group, not from the registry."
            )

    def test_a_registry_view_cannot_list_every_cache_in_the_process(self, registry: Registry) -> None:
        """``cache_entries`` is for the code that builds the process, not for code living in it."""
        with pytest.raises(RuntimeError, match="asked for every cache in the process"):
            registry.for_namespace("orders").cache_entries()

    def test_a_configuration_view_cannot_make_another_agents_view(self, config: Config) -> None:
        with pytest.raises(RuntimeError, match="Views are created from the application's configuration"):
            config.for_namespace("orders").for_namespace("billing")


class TestNoPublicPathToTheLoader:
    """**Configuration is read through the component's own scoped view.**

    *Failure it prevents:* a component reads a neighbour's or the process's value under a name
    that means "mine", and the bug appears only once a second agent exists.
    """

    def test_the_public_configuration_surface_is_exactly_three_names(self) -> None:
        """A new public accessor has to be added to this list, which is where it gets argued.

        ``config`` is the read path and returns a view; ``configure`` and ``has_config`` are the
        application's injection point. Anything else public that hands out configuration is a
        second read path, and the class-level accessor that existed before this feature was
        deleted for exactly that reason.
        """
        on_component = {name for name in dir(Component) if "config" in name.lower() and not name.startswith("_")}
        on_metaclass = {name for name in dir(type(Component)) if "config" in name.lower() and not name.startswith("_")}

        assert on_component | on_metaclass == {"config", "configure", "has_config"}, (
            "the public configuration surface of Component changed. There is no public read path to the unscoped "
            "loader: config is a view, configure and has_config are the application's injection point. A new public "
            "accessor is a second read path, and a component reading the unscoped tree reads a neighbour's value "
            "under a name that means 'mine'."
        )

    def test_no_public_attribute_hands_out_the_loader(self, config: Config) -> None:
        Component.configure(config)

        exposed = [
            name
            for subject in (Component, type(Component))
            for name in dir(subject)
            if not name.startswith("_") and getattr(subject, name, None) is config
        ]

        assert not exposed, f"{', '.join(exposed)} hands out the application's own configuration object."

    def test_a_namespaced_component_reads_through_its_own_view(self, config: Config) -> None:
        Component.configure(config)
        Component.init_registry(Registry(Component))

        with namespace_scope("orders"):
            service = StubService()

        assert service.config.is_view
        assert service.config.agent_scope == "orders"
        assert service.config.get("model_name") == "orders-model"

    def test_a_root_component_reads_the_configuration_itself(self, config: Config) -> None:
        """The documented exception, asserted so that it stays an exception and not a habit.

        The root namespace *is* the unscoped configuration, so a root component gets the object
        itself. That is what keeps every existing single-agent application reading what it read
        before; it is not a hole, because a root component has no neighbour to read from.
        """
        Component.configure(config)
        Component.init_registry(Registry(Component))

        assert StubService().config is config


# ----------------------------------------------------------------------------------------------
# Names that leave the process.
# ----------------------------------------------------------------------------------------------


def group_with_agent(name: str) -> Callable[[], None]:
    """A group literally declaring one agent under ``name``."""

    def declare() -> None:
        AgentGroup("a_group", {name: AppBuilder()})

    return declare


def group_config_with_agent(name: str, tmp_path: Path, config: Config) -> Callable[[], None]:
    """The deployment route to the same name: an agent map and a group naming it."""
    (tmp_path / "agents.toml").write_text(f'[agents."{name}"]\nmodule = "a.module:declaration"\n')

    def resolve() -> None:
        GroupConfig.resolve(config, environ={"BLUEPRINT_AGENTS": name})

    return resolve


NAMESPACE_ENTRY_POINTS: dict[str, Callable[[str], Callable[[], Any]]] = {
    "validate_namespace": lambda name: lambda: validate_namespace(name),
    "namespace_scope": lambda name: lambda: namespace_scope(name).__enter__(),
    "Component(namespace=)": lambda name: lambda: StubService(namespace=name),
    "AppBuilder.host_agent": lambda name: lambda: AppBuilder().host_agent(name),
    "AgentGroup": group_with_agent,
}
"""Every way a namespace enters the framework, keyed by how the failure should read.

The namespace becomes a registry key prefix, a NATS queue group, part of a JetStream durable and
a telemetry service name. Four consumers, four different repairs -- so one repaired value is four
names for one agent, which is why every one of these refuses instead.
"""

ILLEGAL_NAMESPACES = ["Orders", "orders-eu", " orders ", "1st", "orders.eu", "orders/eu", "orders>eu"]
"""Each one legal to some consumer and fatal to another. ``-`` is the durable-name separator."""


class TestNamesAreValidatedNeverRepaired:
    """**A name that crosses the process boundary is validated, never repaired.**

    *Failure it prevents:* silent rewriting breaks an external dependency with nothing in the
    logs to debug. A namespace lower-cased for the filesystem is one agent under two names, one
    in the registry and another on the broker; nothing reports the second.
    """

    @pytest.mark.parametrize("entry_point", sorted(NAMESPACE_ENTRY_POINTS))
    @pytest.mark.parametrize("name", ILLEGAL_NAMESPACES)
    def test_an_illegal_namespace_is_refused(self, entry_point: str, name: str) -> None:
        Component.init_registry(Registry(Component))

        with pytest.raises(ValueError) as refusal:
            NAMESPACE_ENTRY_POINTS[entry_point](name)()

        assert name.strip() in str(refusal.value) or repr(name) in str(refusal.value), (
            f"{entry_point} refused {name!r} without naming it. A name that crosses the process boundary is "
            "validated, never repaired -- and the refusal has to say which value, because the author sees only "
            "the value they wrote."
        )

    @pytest.mark.parametrize("name", [name for name in ILLEGAL_NAMESPACES if name == name.strip()] + [" Orders "])
    def test_the_deployment_route_refuses_the_same_names(self, name: str, tmp_path: Path, config: Config) -> None:
        """Same alphabet from the group file, so a typo fails at startup instead of inside a constructor.

        The agent list is a list -- a comma-separated environment variable, or a YAML sequence --
        and both routes strip each element before validating it. That is list parsing, not name
        repair: ``BLUEPRINT_AGENTS="orders, billing"`` has to work, and the whitespace belongs to
        the separator rather than to either name. So the padded-only case is excluded here and
        ``" Orders "`` takes its place: the element is trimmed, and then held to the alphabet
        exactly like any other, which is what keeps the trim from becoming a general repair.
        """
        with pytest.raises(GroupConfigError, match="cannot be a namespace"):
            group_config_with_agent(name, tmp_path, config)()

    @pytest.mark.parametrize("name", ["orders", "orders_eu", "a", "a1"])
    def test_a_legal_namespace_comes_back_unchanged(self, name: str) -> None:
        assert validate_namespace(name) == name

    @pytest.mark.parametrize("name", ["Sessions", "../evil", "a b", "_leading", "a/b"])
    def test_an_illegal_cache_name_is_refused(self, name: str) -> None:
        """A cache name becomes a directory and a Redis key prefix, so a repair writes elsewhere."""
        with pytest.raises(ValueError, match="not a legal cache name"):
            CacheBackendFactory.validate_name(name)

    @pytest.mark.parametrize("name", ["Sessions", "../evil"])
    def test_an_illegal_cache_name_is_refused_where_it_is_declared(self, name: str) -> None:
        """At the ``with_cache`` call, not at ``build()``: a check answerable at the call stays there."""
        with pytest.raises(ValueError, match="not a legal cache name"):
            AppBuilder().with_cache(name=name)


# ----------------------------------------------------------------------------------------------
# The two rules that are about the source tree rather than about its behaviour. Both read the
# files and parse them, because both failures are invisible at runtime: import-time logging
# configuration works perfectly until an application disagrees with it, and a print goes to a
# stream nobody collects.
# ----------------------------------------------------------------------------------------------

LOGGING_CONFIGURATION_CALLS = frozenset({"basicConfig", "dictConfig", "fileConfig", "addHandler", "setFormatter", "addFilter", "setLevel"})
"""Calls that configure logging rather than emit a record: handlers, formatters, filters, levels."""

LOGGING_OWNER = FRAMEWORK / "config" / "custom_logging.py"
"""``LoggingManager``: the one place in the framework allowed to configure logging, once, for the
application that asked it to."""

ALLOWED_PRINTS = {
    FRAMEWORK / "entrypoint.py": "a group that cannot start must say so on stderr, before AppBuilder configures logging",
    LOGGING_OWNER: "the fallback for a failure of logging configuration itself, which cannot be logged",
}
"""The framework's two deliberate writes to stderr, with the reason each one cannot be a log call.

Both happen where no logging configuration can be relied on. Anything else is a diagnostic, and a
diagnostic that bypasses the logger cannot be silenced, levelled or formatted by the application
carrying it.
"""


def python_files(root: Path) -> list[Path]:
    """Every Python module under ``root``, excluding the caches."""
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def calls_in(path: Path, wanted: Callable[[ast.Call], str | None]) -> list[tuple[int, str, bool]]:
    """Return ``(line, what, at_import_time)`` for every call in ``path`` that ``wanted`` names.

    ``at_import_time`` is what distinguishes a rule violation from a legitimate entry point: a
    call inside a function runs when the application calls it, and the same call at module level
    runs for anyone who so much as imports the module.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    inside_function: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            for descendant in ast.walk(node):
                inside_function.add(descendant)

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (what := wanted(node)) is not None:
            found.append((node.lineno, what, node not in inside_function))
    return found


def logging_configuration(node: ast.Call) -> str | None:
    """Name the logging-configuration call this node makes, if it makes one."""
    if isinstance(node.func, ast.Attribute) and node.func.attr in LOGGING_CONFIGURATION_CALLS:
        return node.func.attr
    return None


def print_call(node: ast.Call) -> str | None:
    """Name a call to the builtin ``print``, if that is what this node is."""
    if isinstance(node.func, ast.Name) and node.func.id == "print":
        return "print"
    return None


class TestLoggingIsConfiguredByTheApplication:
    """**Logging is configured by the application**, never by library code or at import time.

    *Failure it prevents:* whoever loads first decides the whole process's logging. An
    import-time ``basicConfig`` installs a root handler, and every later configuration -- the
    application's own, or a CLI's ``--verbose`` -- then finds the root already configured and
    does nothing. The symptom is a flag that has no effect, with nothing to point at.
    """

    @pytest.mark.parametrize("path", python_files(REPO_ROOT / "src"), ids=lambda path: str(path.relative_to(REPO_ROOT)))
    def test_no_module_configures_logging_at_import_time(self, path: Path) -> None:
        at_import_time = [(line, what) for line, what, import_time in calls_in(path, logging_configuration) if import_time]

        assert not at_import_time, (
            f"{path.relative_to(REPO_ROOT)} configures logging at import time: "
            f"{', '.join(f'{what}() on line {line}' for line, what in at_import_time)}. Logging is configured by the "
            "application, and importing a module is not the application deciding anything -- the root logger is "
            "configured by whoever imports first, and every later configuration silently does nothing."
        )

    @pytest.mark.parametrize(
        "path", [path for path in python_files(FRAMEWORK) if path != LOGGING_OWNER], ids=lambda path: str(path.relative_to(REPO_ROOT))
    )
    def test_only_the_logging_manager_configures_logging(self, path: Path) -> None:
        """Inside the framework, which is library code from end to end, there is one owner."""
        configuration = calls_in(path, logging_configuration)

        assert not configuration, (
            f"{path.relative_to(REPO_ROOT)} configures logging: "
            f"{', '.join(f'{what}() on line {line}' for line, what, _ in configuration)}. The framework is library "
            "code: it emits through getLogger(__name__) and configures nothing. LoggingManager is the one owner, "
            "driven by the application's log_level, log_format and suppress_noisy_loggers."
        )


class TestNoDiagnosticsViaPrint:
    """**No diagnostics via print.** The framework emits through a logger.

    *Failure it prevents:* output the application cannot silence, level, format or route, in a
    container where stdout is the log stream. Two writes to stderr survive, both from before
    logging configuration can be relied on, and both are listed with their reason.

    Scope is the framework. ``src/blueprint/agent_generator`` is a command-line tool whose
    standard output is its interface to the developer running it, not a diagnostic channel.
    """

    @pytest.mark.parametrize(
        "path", [path for path in python_files(FRAMEWORK) if path not in ALLOWED_PRINTS], ids=lambda path: str(path.relative_to(REPO_ROOT))
    )
    def test_the_framework_prints_nothing(self, path: Path) -> None:
        prints = calls_in(path, print_call)

        assert not prints, (
            f"{path.relative_to(REPO_ROOT)} prints on line(s) {', '.join(str(line) for line, _, _ in prints)}. Use "
            "getLogger(__name__): print() bypasses the logging infrastructure, so the application cannot silence, "
            "level or format it, and in a container it lands in the log stream unstructured."
        )

    @pytest.mark.parametrize("path", sorted(ALLOWED_PRINTS), ids=lambda path: str(path.relative_to(REPO_ROOT)))
    def test_every_allowed_print_still_writes_to_stderr(self, path: Path) -> None:
        """The allowance is for a message that cannot be logged, and it goes where errors go."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and print_call(node)]
        assert calls, f"{path.relative_to(REPO_ROOT)} no longer prints; remove it from ALLOWED_PRINTS."

        for node in calls:
            streams = [keyword.value for keyword in node.keywords if keyword.arg == "file"]
            rendered = [ast.unparse(stream) for stream in streams]
            assert rendered == ["sys.stderr"], (
                f"{path.relative_to(REPO_ROOT)} line {node.lineno} prints to {rendered or 'stdout'}. The two "
                f"allowed prints exist because {ALLOWED_PRINTS[path]}, and a message that replaces a log record "
                "belongs on stderr."
            )


# ----------------------------------------------------------------------------------------------
# References. The guard that would have caught AGENTS.md, and the reason the rest of this file
# stays findable.
# ----------------------------------------------------------------------------------------------

LINK = re.compile(r"\]\(\s*([^)\s]+)")
"""Every markdown link target, whatever its text. Written to match the ``](target)`` half so that
a nested form -- a badge image inside a link -- is read rather than skipped."""

TICKED = re.compile(r"`([^`\n]+)`")
"""Backticked spans: how this repository cites a file when it is not making a link of it."""

REFERENCE_SUFFIXES = frozenset({".md", ".py", ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini", ".txt", ".sh"})
"""Suffixes that make a backticked token a file reference rather than an expression."""

SEARCH_ROOTS = ("", "src/blueprint/agents", "tests/unit/agents")
"""Where a relative reference is looked for, besides the citing document's own directory.

This repository writes paths relative to the tree under discussion -- ``component/namespace.py``
means the framework package, ``app_builder/test_app_builder.py`` means the unit tests -- so those
two trees are roots as well as the repository itself.
"""

HISTORICAL_DOCUMENTS = ("docs/plans", "docs/specs", "CHANGELOG.md")
"""Documents that record what was decided and what was done, at the time it was done.

They name files that have since been deleted, and proposals name files not yet written; both are
correct in a record. Their **links** are still checked -- a link is an invitation to click -- but
their citations are not held to the tree as it stands today.
"""

PROJECT_FACING_DOCUMENTS = ("docs/guides", "docs/getting-started.md", "src/blueprint/agent_generator")
"""Documents that describe the reader's generated project -- ``src/main.py``, ``settings.toml`` --
rather than this repository. The paths in them resolve in a project this tool creates."""

EXCLUDED_FROM_THE_REPOSITORY = ("docs/adr", "CLAUDE.local.md")
"""Present in a working copy but not part of the repository: ADRs are authored and owned outside
it, and ``CLAUDE.local.md`` is one developer's machine. Neither is scanned, so that this guard
gives the same answer everywhere."""

KNOWN_GAPS: dict[tuple[str, str], str] = {
    ("README.md", "LICENSE"): (
        "README states the MIT licence and pyproject.toml carries the MIT classifier, but no LICENSE file has ever "
        "been committed. Adding one is a legal artefact and a human decision, not a documentation fix."
    ),
}
"""References that are known not to resolve, each with why it has not been fixed.

Listed rather than silently tolerated, and held to being genuinely broken by
:meth:`TestEveryReferenceResolves.test_no_known_gap_has_quietly_been_fixed` -- an allowlist that
outlives its entries is how a guard stops guarding.
"""


def strip_code(text: str) -> str:
    """Drop fenced code blocks, whose contents are code rather than references."""
    kept, inside = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            inside = not inside
            continue
        kept.append("" if inside else line)
    return "\n".join(kept)


def all_markdown() -> Iterator[Path]:
    """Every markdown file present, ignoring the dot directories and the vendored trees."""
    for path in REPO_ROOT.rglob("*.md"):
        parts = path.relative_to(REPO_ROOT).parts
        if not any(part.startswith(".") or part in {"node_modules", "__pycache__"} for part in parts):
            yield path


def markdown_documents() -> list[Path]:
    """Every markdown document this guard reads, in a stable order."""
    excluded = {(REPO_ROOT / part) for part in EXCLUDED_FROM_THE_REPOSITORY}
    return sorted(path for path in all_markdown() if not any(path == item or item in path.parents for item in excluded))


def every_markdown_name() -> set[str]:
    """The file name of every markdown document present, scanned or not.

    Wider than :func:`markdown_documents` on purpose: a document cited by name exists if a file
    of that name is here, whether or not this guard reads it. An ADR is owned outside the
    repository and is not scanned, but citing one is not a dead pointer.
    """
    return {path.name for path in all_markdown()}


def document_id(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def is_a(path: Path, group: tuple[str, ...]) -> bool:
    return document_id(path).startswith(group)


def resolves(token: str, origin: Path) -> bool:
    """Whether ``token``, cited in ``origin``, names a file that exists."""
    if (origin.parent / token).exists():
        return True
    return any((REPO_ROOT / root / token).exists() for root in SEARCH_ROOTS)


def link_targets(text: str) -> Iterator[str]:
    """Every link target that names a file in this repository."""
    for raw in LINK.findall(strip_code(text)):
        target = raw.strip("<>").split("#")[0]
        if not target or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            continue
        yield target.lstrip("/")


def cited_paths(text: str) -> Iterator[str]:
    """Every backticked token that names a file: a path, or a document by name."""
    for raw in TICKED.findall(strip_code(text)):
        token = raw.strip().split(":")[0]
        if not token or " " in token or "<" in token or "..." in token:
            continue
        if Path(token).suffix not in REFERENCE_SUFFIXES:
            continue
        if "/" not in token and not token.endswith(".md"):
            continue
        yield token


class TestEveryReferenceResolves:
    """**A reference points at a file that exists.**

    *Failure it prevents:* the one this file exists because of. ``CLAUDE.md`` said "see
    ``AGENTS.md``" for months, another document quoted what that file "states", and no such file
    had ever been committed -- it was cited into existence. A rule recorded in a document nobody
    can reach is back to being a paragraph, so this is what makes the rest of this file durable.

    A bare document name is checked everywhere, because that is the form the ``AGENTS.md`` case
    took. Path citations are checked in the documents that describe this repository as it stands;
    see :data:`HISTORICAL_DOCUMENTS` and :data:`PROJECT_FACING_DOCUMENTS` for the two kinds that
    are not, and why.
    """

    @pytest.mark.parametrize("document", markdown_documents(), ids=document_id)
    def test_every_link_resolves(self, document: Path) -> None:
        broken = [
            target
            for target in link_targets(document.read_text(encoding="utf-8"))
            if not resolves(target, document) and (document_id(document), target) not in KNOWN_GAPS
        ]

        assert not broken, (
            f"{document_id(document)} links to {', '.join(sorted(set(broken)))}, which does not exist. A reference "
            "points at a file that exists: AGENTS.md was cited for months without existing, and a rule recorded in "
            "a document nobody can reach is not recorded."
        )

    @pytest.mark.parametrize(
        "document",
        [path for path in markdown_documents() if not is_a(path, HISTORICAL_DOCUMENTS) and not is_a(path, PROJECT_FACING_DOCUMENTS)],
        ids=document_id,
    )
    def test_every_cited_path_resolves(self, document: Path) -> None:
        broken = [
            token
            for token in cited_paths(document.read_text(encoding="utf-8"))
            if not resolves(token, document) and (document_id(document), token) not in KNOWN_GAPS
        ]

        assert not broken, (
            f"{document_id(document)} cites {', '.join(sorted(set(broken)))}, which does not exist. Either the file "
            "moved and the citation did not, or the citation named a file that was never written -- which is exactly "
            "how AGENTS.md came to be cited for months without existing."
        )

    @pytest.mark.parametrize("document", [path for path in markdown_documents() if not is_a(path, HISTORICAL_DOCUMENTS)], ids=document_id)
    def test_a_document_cited_by_name_exists_somewhere(self, document: Path) -> None:
        """The ``AGENTS.md`` case itself: a document pointed at by name has to be a document.

        A bare ``FOO.md`` in backticks is a pointer to a document, not a path relative to
        anything, so it is satisfied by a file of that name anywhere in the repository --
        including the files this guard does not itself scan, since existing and being scanned are
        different questions.

        Not run over the records, for the reason a record exists: a proposal names the documents
        it intends to write, and the alternatives it rejected, and both would fail here. The
        citation that motivated this check was in ``CLAUDE.md``, which is not a record.
        """
        names = {name for name in (Path(token).name for token in cited_paths(document.read_text(encoding="utf-8"))) if name.endswith(".md")}
        known = every_markdown_name()
        missing = sorted(name for name in names - known if (document_id(document), name) not in KNOWN_GAPS)

        assert not missing, (
            f"{document_id(document)} cites the document(s) {', '.join(missing)}, which do not exist anywhere in "
            "the repository. Write them, or stop pointing at them: AGENTS.md spent months being cited into "
            "existence, and docs/plans/2026-06-10-sessions-job-handler.md went as far as quoting what it 'states'."
        )

    @pytest.mark.parametrize(("where", "reason"), sorted(KNOWN_GAPS.items()))
    def test_no_known_gap_has_quietly_been_fixed(self, where: tuple[str, str], reason: str) -> None:
        """An allowlist that outlives its entries is how a guard stops guarding."""
        document, token = where
        complaint = f"{document} now resolves '{token}', so remove it from KNOWN_GAPS. It was listed because: {reason}"

        assert not resolves(token, REPO_ROOT / document), complaint
