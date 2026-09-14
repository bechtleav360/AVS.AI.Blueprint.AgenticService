"""The declaration surface and ``AgentGroup``'s replay must agree, and cannot drift apart.

Adding a capability to the framework is now **one** edit -- a ``with_*`` method on
``AppBuilder`` -- which is the whole point of phase 8b. But the group still has to be able to
move a recorded call from one builder to another, and ``Declaration.replay`` does that by
resolving ``with_<kind>`` with ``getattr``. So there are exactly two ways for the two halves to
part company:

- a ``with_*`` method records a ``kind`` that no method answers to, and replay dies with an
  ``AttributeError`` at assembly -- in a group, never standalone;
- a ``with_*`` method whose replayed arguments do not reproduce the call, so an agent is
  assembled from a declaration that says something slightly different from what its ``main.py``
  said.

Neither is visible in a single-agent application, and both would be found in production by
somebody grouping two agents. Hence a gate: every public declaration method is called
reflectively, its declaration is replayed onto a fresh builder, and the result must be equal to
what was recorded.

**A new ``with_*`` method fails this file until it is listed in ``SAMPLE_CALLS``.** That is
deliberate -- the list is what proves the method was thought about -- and the failure message
says so.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from blueprint.agents.agent.agent_builder import AgentBuilder
from blueprint.agents.app_builder import AppBuilder, Declaration
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.io.api.actuators.health.health_base import HealthCheckerBase
from blueprint.agents.io.api.rest_api_base import RestApiBase
from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase
from blueprint.agents.models.api import ComponentHealth
from blueprint.agents.services.service_base import ServiceBase

from .conftest import StubHandler


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


SAMPLE_CALLS: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {
    "with_handler": ((StubHandler,), {"name": "a_handler"}),
    "with_service": ((StubService,), {"name": "a_service"}),
    "with_agent": ((AgentBuilder(runtime_name="a_runtime"),), {}),
    "with_scheduler": ((StubScheduler,), {"name": "a_scheduler"}),
    "with_rest_api": ((StubApi,), {"name": "an_api"}),
    "with_cache": ((), {"name": "a_cache"}),
    "with_health_checker": (("a_check", StubChecker()), {}),
}
"""One call per declaration method, as a project would write it.

Keyword arguments are given where the method takes a name, because a name is the part replay is
most able to lose: ``with_health_checker`` takes it positionally and every other method takes it
as a keyword, and that irregularity lives in exactly one branch of ``Declaration.replay``.
"""


def declaration_methods() -> list[str]:
    """Every public declaration method on ``AppBuilder``, discovered rather than listed.

    Discovered, so that a method added without a sample call fails this file instead of being
    quietly untested. The ``with_`` prefix is what makes a method a declaration: ``host_agent``
    records no ``Declaration`` -- it states a fact about the process -- and is not one of these.
    """
    return sorted(name for name in dir(AppBuilder) if name.startswith("with_"))


def registry_contents() -> dict[str, object]:
    """Every component in the shared registry, or nothing when there is not even a registry yet.

    Read through ``_components`` because there is no public "list everything" method, and there
    should not be: C6 keeps a process-wide view out of reach of the components themselves.
    """
    registry = Component.shared_registry
    return dict(registry._components) if registry is not None else {}


class TestEveryDeclarationMethodIsCovered:
    def test_the_sample_calls_name_every_method(self) -> None:
        missing = set(declaration_methods()) - set(SAMPLE_CALLS)
        assert not missing, (
            f"{', '.join(sorted(missing))} is a declaration method with no sample call in this file. Add one: the "
            "list is what proves a new with_* was checked against the group's replay, which is the only place a "
            "recorder and its API can drift apart."
        )

    def test_the_sample_calls_name_nothing_that_is_gone(self) -> None:
        extra = set(SAMPLE_CALLS) - set(declaration_methods())
        assert not extra, f"{', '.join(sorted(extra))} no longer exists on AppBuilder; remove the sample call."


@pytest.mark.parametrize("method", declaration_methods())
class TestRecordingAndReplayAgree:
    def test_the_call_records_exactly_one_declaration(self, mock_config: MagicMock, method: str) -> None:
        builder = AppBuilder()
        arguments, keywords = SAMPLE_CALLS[method]

        getattr(builder, method)(*arguments, **keywords)

        assert len(builder.declarations) == 1

    def test_nothing_is_constructed_by_recording_it(self, mock_config: MagicMock, method: str) -> None:
        """Collect, then wire: a component built during accumulation belongs to the root for ever."""
        builder = AppBuilder()
        arguments, keywords = SAMPLE_CALLS[method]
        before = registry_contents()

        getattr(builder, method)(*arguments, **keywords)

        assert registry_contents() == before

    def test_replay_reproduces_the_declaration(self, mock_config: MagicMock, method: str) -> None:
        """What a group does to move an agent's calls onto the root builder, and it must be lossless."""
        source = AppBuilder()
        arguments, keywords = SAMPLE_CALLS[method]
        getattr(source, method)(*arguments, **keywords)

        target = AppBuilder()
        for declaration in source.declarations:
            declaration.replay(target)

        assert target.declarations == source.declarations

    def test_replay_takes_the_namespace_from_the_scope_it_runs_in(self, mock_config: MagicMock, method: str) -> None:
        """The ambient mechanism: no namespace is passed, and none appears in any signature."""
        source = AppBuilder()
        arguments, keywords = SAMPLE_CALLS[method]
        getattr(source, method)(*arguments, **keywords)

        target = AppBuilder()
        with namespace_scope("orders"):
            for declaration in source.declarations:
                declaration.replay(target)

        assert [entry.namespace for entry in target.declarations] == ["orders"]
        assert [entry.namespace for entry in source.declarations] == [""]

    def test_the_recorded_kind_has_a_method_to_replay_onto(self, mock_config: MagicMock, method: str) -> None:
        """``Declaration.replay`` resolves ``with_<kind>`` with getattr, and this is that contract."""
        builder = AppBuilder()
        arguments, keywords = SAMPLE_CALLS[method]

        getattr(builder, method)(*arguments, **keywords)

        for declaration in builder.declarations:
            assert hasattr(AppBuilder, f"with_{declaration.kind}"), (
                f"{method}() records kind '{declaration.kind}', but there is no with_{declaration.kind}() for "
                "Declaration.replay to call. A group would fail at assembly with an AttributeError while the same "
                "declaration worked standalone."
            )


class TestTheNameSurvivesTheIrregularSignature:
    """``with_health_checker(name, checker)`` is the one method whose name is positional."""

    def test_a_replayed_checker_keeps_its_name(self, mock_config: MagicMock) -> None:
        checker = StubChecker()
        source = AppBuilder().with_health_checker("db", checker)

        target = AppBuilder()
        for declaration in source.declarations:
            declaration.replay(target)

        recorded = target.declarations[0]
        assert (recorded.name, recorded.target) == ("db", checker)

    def test_a_replayed_component_keeps_its_name_override(self, mock_config: MagicMock) -> None:
        source = AppBuilder().with_service(StubService, name="planner")

        target = AppBuilder()
        for declaration in source.declarations:
            declaration.replay(target)

        assert target.declarations[0].name == "planner"

    def test_a_replayed_declaration_keeps_its_constructor_arguments(self, mock_config: MagicMock) -> None:
        source = AppBuilder().with_cache(True, False, name="sessions")

        target = AppBuilder()
        for declaration in source.declarations:
            declaration.replay(target)

        assert target.declarations[0] == Declaration(
            kind="cache", target=None, name="sessions", namespace="", kwargs={"enable_locking": False}
        )
