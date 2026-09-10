"""Unit tests for ``AppBuilder`` recording rather than constructing.

The property under test is the one the whole builder unification rests on: a ``with_*()`` call
stores what to build, and ``build()`` is the only thing that builds it. Everything else here --
the single-use guard, where the configuration may be handed over, the declaration-order refusal
-- follows from that one change and is pinned so it cannot drift back.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from blueprint.agents.agent.agent_builder import AgentBuilder
from blueprint.agents.app_builder import AppBuilder, Declaration
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.config import Config
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.services.service_base import ServiceBase

from .conftest import StubHandler, realize


class OrderService(ServiceBase):
    """A service written the way a project writes one: no namespace, no arguments."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class CountingService(ServiceBase):
    """Counts its own constructions, which is how 'nothing is built yet' is observable."""

    built = 0

    def __init__(self) -> None:
        super().__init__()
        CountingService.built += 1

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class FirstHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def can_handle_event(self, event: GenericCloudEvent, context: dict) -> bool:
        return True

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> None:
        return None


class SecondHandler(FirstHandler):
    """Same priority as FirstHandler, so which of them wins is decided by registration order."""


class LowPriorityHandler(FirstHandler):
    def __init__(self) -> None:
        super().__init__(priority=500)


def settings_file(tmp_path: Path, app_name: str = "root-app") -> Path:
    settings = tmp_path / "settings.toml"
    settings.write_text(f'[development]\napp_name = "{app_name}"\napp_port = 8000\n')
    return settings


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(settings_files=[str(settings_file(tmp_path))], root_path=str(tmp_path))


@pytest.fixture(autouse=True)
def reset_counting_service() -> None:
    CountingService.built = 0


class TestNothingIsBuiltUntilBuild:
    def test_a_class_is_not_constructed_by_with_service(self, config: Config) -> None:
        AppBuilder(config).with_service(CountingService)
        assert CountingService.built == 0

    def test_nothing_reaches_the_registry(self, config: Config) -> None:
        """The registry exists -- the builder's own TelemetryManager makes it -- but it is empty."""
        AppBuilder(config).with_service(OrderService).with_handler(StubHandler)
        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component_names_by_type(Component) == []

    def test_a_factory_is_not_called(self, config: Config) -> None:
        calls: list[int] = []
        AppBuilder(config).with_service(lambda: calls.append(1) or CountingService())
        assert calls == []

    def test_build_constructs_it(self, config: Config) -> None:
        AppBuilder(config).with_service(CountingService).build()
        assert CountingService.built == 1

    def test_an_instance_is_the_exception(self, config: Config) -> None:
        """A caller who writes ``with_service(X())`` built it themselves, at that line."""
        Component.configure(config)
        assert CountingService.built == 0

        CountingService()

        assert CountingService.built == 1


class TestWhatIsRecorded:
    def test_the_declarations_are_kept_in_call_order(self, config: Config) -> None:
        builder = AppBuilder(config).with_handler(StubHandler).with_service(OrderService)
        assert [(entry.kind, entry.target) for entry in builder.declarations] == [
            ("handler", StubHandler),
            ("service", OrderService),
        ]

    def test_the_name_and_the_constructor_arguments_are_kept(self, config: Config) -> None:
        builder = AppBuilder(config).with_service(OrderService, name="db", retries=3)
        entry = builder.declarations[0]
        assert (entry.name, entry.kwargs) == ("db", {"retries": 3})

    def test_the_ambient_namespace_is_captured_at_the_call(self, config: Config) -> None:
        """Not looked up at construction time: by then no scope is in force any more."""
        builder = AppBuilder(config)
        with namespace_scope("orders"):
            builder.with_service(OrderService)
        assert builder.declarations[0].namespace == "orders"

    def test_a_namespace_keyword_is_refused(self, config: Config) -> None:
        """It was a parameter until step 4; dropped, it would reach the constructor instead."""
        with pytest.raises(TypeError, match="does not take a namespace"):
            AppBuilder(config).with_service(OrderService, namespace="billing")

    def test_a_cache_is_recorded_too(self, config: Config) -> None:
        builder = AppBuilder(config).with_cache(name="sessions")
        entry = builder.declarations[0]
        assert (entry.kind, entry.name, entry.target) == ("cache", "sessions", None)

    def test_declarations_is_a_snapshot(self, config: Config) -> None:
        builder = AppBuilder(config).with_service(OrderService)
        declared = builder.declarations
        builder.with_handler(StubHandler)
        assert len(declared) == 1

    def test_a_built_component_is_marked_as_built(self, config: Config) -> None:
        Component.configure(config)
        builder = AppBuilder(config).with_service(OrderService()).with_handler(StubHandler)
        assert [entry.is_built for entry in builder.declarations] == [True, False]

    def test_something_that_cannot_be_called_is_refused(self, config: Config) -> None:
        with pytest.raises(TypeError, match="component class, a callable returning one"):
            AppBuilder(config).with_service(42)  # type: ignore[arg-type]


class TestDeclarationOrder:
    def test_an_instance_after_a_class_at_equal_priority_is_refused(self, config: Config) -> None:
        """The instance is already registered, so it would be tried first -- the reverse of the file."""
        builder = AppBuilder(config).with_handler(FirstHandler).with_handler(SecondHandler())

        with pytest.raises(ValueError, match="SecondHandler was passed to with_handler"):
            builder.build()

    def test_the_refusal_names_both_handlers_and_the_priority(self, config: Config) -> None:
        builder = AppBuilder(config).with_handler(FirstHandler).with_handler(SecondHandler())

        with pytest.raises(ValueError, match=r"FirstHandler was declared as a class.*priority 100"):
            builder.build()

    def test_different_priorities_are_accepted(self, config: Config) -> None:
        """Priority decides, so registration order decides nothing and cannot be reversed."""
        builder = AppBuilder(config).with_handler(FirstHandler).with_handler(LowPriorityHandler())

        builder.build()

    def test_an_instance_before_a_class_is_accepted(self, config: Config) -> None:
        """The order the caller wrote is the order construction produces, so nothing is wrong."""
        builder = AppBuilder(config).with_handler(SecondHandler()).with_handler(FirstHandler)

        builder.build()

    def test_two_classes_are_accepted(self, config: Config) -> None:
        AppBuilder(config).with_handler(FirstHandler).with_handler(SecondHandler).build()

    def test_two_agents_do_not_collide(self, config: Config) -> None:
        """Handlers of different agents are never in one chain, so their order is not shared."""
        with namespace_scope("billing"):
            billing_handler = SecondHandler()
        builder = AppBuilder(config)
        with namespace_scope("orders"):
            builder.with_handler(FirstHandler)
        with namespace_scope("billing"):
            builder.with_handler(billing_handler)

        builder.build()


class TestWhereTheConfigurationComesFrom:
    def test_build_accepts_it(self, config: Config) -> None:
        app = AppBuilder().with_service(OrderService).build(config)
        assert app.title == "root-app"

    def test_the_constructor_still_accepts_it(self, config: Config) -> None:
        app = AppBuilder(config).with_service(OrderService).build()
        assert app.title == "root-app"

    def test_giving_it_twice_is_refused(self, config: Config, tmp_path: Path) -> None:
        elsewhere = tmp_path / "other"
        elsewhere.mkdir()
        other = Config(settings_files=[str(settings_file(elsewhere, "other-app"))], root_path=str(elsewhere))
        with pytest.raises(ValueError, match="passed to both AppBuilder"):
            AppBuilder(config).build(other)

    def test_neither_loads_the_default_settings_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``AppBuilder().build()`` is the migrated standalone shape; it has to find settings.toml."""
        settings_file(tmp_path, "found-by-default")
        monkeypatch.chdir(tmp_path)

        app = AppBuilder().with_service(OrderService).build()

        assert app.title == "found-by-default"

    def test_logging_is_configured_when_the_constructor_is_given_one(self, tmp_path: Path) -> None:
        config = MagicMock(spec=Config)
        AppBuilder(config)
        config.configure_logging.assert_called_once()

    def test_logging_is_configured_by_build_otherwise(self, config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[int] = []
        monkeypatch.setattr(Config, "configure_logging", lambda self: calls.append(1))
        builder = AppBuilder().with_service(OrderService)
        assert calls == []

        builder.build(config)

        assert calls == [1]


class TestSingleUse:
    def test_building_twice_is_refused(self, config: Config) -> None:
        builder = AppBuilder(config).with_service(OrderService)
        builder.build()

        with pytest.raises(RuntimeError, match="already been built"):
            builder.build()

    def test_the_second_call_reports_the_builder_not_the_config(self, config: Config) -> None:
        """Previously this surfaced as Component.configure's 'already set', three frames down."""
        builder = AppBuilder(config)
        builder.build()

        with pytest.raises(RuntimeError, match="a builder produces one application"):
            builder.build()


class TestAnApplicationWithNoComponents:
    def test_it_builds(self, config: Config) -> None:
        """Nothing constructs a registry when nothing is declared, so build() has to."""
        app = AppBuilder(config).build()
        assert app.title == "root-app"

    def test_the_registry_exists_afterwards(self, config: Config) -> None:
        AppBuilder(config).build()
        assert Component.shared_registry is not None


class TestRealizeMatchesBuild:
    def test_the_same_components_are_registered(self, config: Config) -> None:
        """The test helper runs build()'s own replay pass, so it cannot drift from it."""
        realize(AppBuilder(config).with_service(OrderService))
        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("order_service").namespace == ""


class TestTheDeclarationValueObject:
    def test_a_class_is_not_built(self) -> None:
        assert Declaration(kind="service", target=OrderService, name=None, namespace="", kwargs={}).is_built is False

    def test_a_component_is_built(self, config: Config) -> None:
        Component.configure(config)
        assert Declaration(kind="service", target=OrderService(), name=None, namespace="", kwargs={}).is_built is True


class TestAnUnbuiltAgentBuilder:
    """D6: with_agent takes the builder itself, and build() hands it this agent's config view."""

    def test_it_is_recorded_rather_than_refused(self, config: Config) -> None:
        """An AgentBuilder is neither a Component nor callable, so _record has to know it."""
        agent = AgentBuilder(runtime_name="orders").with_model_from_config()
        builder = AppBuilder(config).with_agent(agent)
        assert builder.declarations[0].target is agent

    def test_it_is_not_built_by_the_with_call(self, config: Config) -> None:
        agent = AgentBuilder(runtime_name="orders").with_model_from_config()
        AppBuilder(config).with_agent(agent)
        assert agent._ai_config is None

    def test_build_hands_it_the_namespace_scoped_view(self, config: Config) -> None:
        """The bug D6 removes: a lambda closes over whichever config was in scope where it was
        written, which in a group is a neighbour's. The view is passed in instead."""
        agent = AgentBuilder(runtime_name="orders")
        seen: list[Config] = []
        agent.build = lambda cfg=None, **kwargs: seen.append(cfg) or MagicMock()  # type: ignore[method-assign]

        builder = AppBuilder(config)
        with namespace_scope("orders"):
            builder.with_agent(agent)
        builder.build()

        assert len(seen) == 1
        assert seen[0] is config.for_namespace("orders")

    def test_a_root_agent_gets_the_loader_itself(self, config: Config) -> None:
        """for_namespace("") returns the loader, so a single-agent app is unchanged."""
        agent = AgentBuilder(runtime_name="orders")
        seen: list[Config] = []
        agent.build = lambda cfg=None, **kwargs: seen.append(cfg) or MagicMock()  # type: ignore[method-assign]

        AppBuilder(config).with_agent(agent).build()

        assert seen == [config]

    def test_constructor_arguments_are_forwarded_to_build(self, config: Config) -> None:
        seen: list[dict] = []
        agent = AgentBuilder(runtime_name="orders")
        agent.build = lambda cfg=None, **kwargs: seen.append(kwargs) or MagicMock()  # type: ignore[method-assign]

        AppBuilder(config).with_agent(agent, retries=3).build()

        assert seen == [{"retries": 3}]

    def test_it_is_refused_by_the_other_with_methods(self, config: Config) -> None:
        agent = AgentBuilder(runtime_name="orders")
        with pytest.raises(TypeError, match="belongs in with_agent"):
            AppBuilder(config).with_service(agent)  # type: ignore[arg-type]
