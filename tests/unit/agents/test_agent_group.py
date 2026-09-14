"""Collecting several agents into one process: what a group accepts, and what it refuses.

``AgentGroup`` is the only object that knows several agents can share a process, and it is
therefore the only one that imposes the group's rules. Two properties are under test here and
neither belongs to ``AppBuilder``:

- **Assembly.** Named, unbuilt declarations in; one application out, with each agent's recorded
  calls replayed inside its own namespace.
- **Refusal.** Everything a group cannot honour, refused at assembly with a message naming the
  agent -- while the same declaration goes on working standalone, which is what
  *standalone is permissive, the group has rules* means.

``from_config`` performs no I/O, which is why the ``GroupConfig`` here is always constructed
literally: these cases state exact compositions without arranging anything around the code under
test. Importing an agent's module is the one thing it reaches outside for, and that is driven
entirely by the ``module`` strings the group carries -- so the declarations below live in this
file and are named by their real dotted paths.
"""

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.agent_group import AgentGroup
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.config import Config
from blueprint.agents.group_config import AgentSpec, GroupConfig, GroupConfigError
from blueprint.agents.models.config import CacheConfig
from blueprint.agents.services.service_base import ServiceBase

_THIS = "tests.unit.agents.test_agent_group"


class OrderService(ServiceBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class BillingService(ServiceBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


# The module-level declarations a group's `module` strings point at, exactly as an agent's own
# module would expose them: an AppBuilder that has never been built.
order_declaration = AppBuilder().with_service(OrderService)
billing_declaration = AppBuilder().with_service(BillingService)
not_a_declaration = "this is not an AppBuilder"


def registry() -> Any:
    """The process's registry, which every assertion below reads after assembly."""
    assert Component.shared_registry is not None
    return Component.shared_registry


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
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_environment = "development"\napp_name = "the-process"\napp_port = 8000\n\n'
        "[development.order]\napp_port = 8000\n\n"
        "[development.billing]\napp_port = 8000\n"
    )
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


def spec(name: str, attribute: str, *, critical: bool = True) -> AgentSpec:
    return AgentSpec(name=name, module=f"{_THIS}:{attribute}", critical=critical)


def component_names() -> list[str]:
    registry = Component.shared_registry
    if registry is None:
        return []
    return sorted(registry.get_component_names_by_type(Component))


def service_names() -> list[str]:
    registry = Component.shared_registry
    if registry is None:
        return []
    return sorted(registry.get_component_names_by_type(ServiceBase))


class TestOneNamespacePerAgent:
    def test_each_agent_is_assembled_under_its_own_name(self, config: Config) -> None:
        group = AgentGroup("finance", {"order": order_declaration, "billing": billing_declaration})

        group.assemble(config)

        assert service_names() == ["billing_billing_service", "order_order_service"]

    def test_a_group_of_one_is_an_ordinary_group(self, config: Config) -> None:
        """Group size 1 is how an agent gets a process to itself; nothing about it is special."""
        AgentGroup("just-order", {"order": order_declaration}).assemble(config)

        assert service_names() == ["order_order_service"]

    def test_the_same_declaration_can_serve_two_agents(self, config: Config) -> None:
        """One declaration, replayed per agent -- the property the whole design rests on."""
        AgentGroup("two", {"order": order_declaration, "billing": order_declaration}).assemble(config)

        assert service_names() == ["billing_order_service", "order_order_service"]

    def test_a_declaration_is_not_consumed_by_being_assembled(self, config: Config) -> None:
        """Replay reads the declarations; it does not build the agent's own builder."""
        AgentGroup("finance", {"order": order_declaration}).assemble(config)

        assert order_declaration.is_built is False
        assert len(order_declaration.declarations) == 1

    def test_the_root_builder_hosts_every_agent(self, config: Config) -> None:
        """build() wires one transport per hosted agent, so the list has to reach it."""
        group = AgentGroup("finance", {"order": order_declaration, "billing": billing_declaration})

        app = group.assemble(config)

        assert app is not None
        assert service_names() == ["billing_billing_service", "order_order_service"]

    def test_it_returns_one_application(self, config: Config) -> None:
        assert AgentGroup("finance", {"order": order_declaration}).assemble(config).title == "the-process"

    def test_an_empty_group_still_builds(self, config: Config) -> None:
        """A process hosting nothing is a legitimate, if useless, thing to assemble."""
        assert AgentGroup("empty", {}).assemble(config) is not None


class TestAgentNames:
    def test_an_illegal_name_is_refused(self) -> None:
        with pytest.raises(ValueError, match="legal namespace"):
            AgentGroup("finance", {"Order": order_declaration})

    def test_the_root_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be named"):
            AgentGroup("finance", {"": order_declaration})

    def test_the_names_are_kept_in_order(self) -> None:
        group = AgentGroup("finance", {"order": order_declaration, "billing": billing_declaration})
        assert list(group.agents) == ["order", "billing"]

    def test_the_group_name_is_readable(self) -> None:
        assert AgentGroup("finance", {}).name == "finance"


class TestWhatAGroupRefuses:
    """Spec sec. 4.2's table. Each of these works standalone and will go on working."""

    def test_a_declaration_that_brought_its_own_config_is_refused(self, config: Config) -> None:
        group = AgentGroup("finance", {"order": AppBuilder(config).with_service(OrderService)})

        with pytest.raises(ValueError, match="one process has one settings tree"):
            group.assemble(config)

    def test_that_refusal_names_the_agent_and_the_fix(self, config: Config) -> None:
        group = AgentGroup("finance", {"order": AppBuilder(config)})

        with pytest.raises(ValueError, match=r"Agent 'order'.*AppBuilder\(\) with no argument"):
            group.assemble(config)

    def test_an_already_built_declaration_is_refused(self, config: Config) -> None:
        """Checked before the configuration rule: build() adopts a config, so a built builder
        reports one too, and the configuration message would otherwise be the only one seen."""
        already = AppBuilder().with_service(OrderService)
        already.build(config)
        Component.reset_shared_state()

        with pytest.raises(ValueError, match="has already been built"):
            AgentGroup("finance", {"order": already}).assemble(config)

    def test_an_instance_is_refused(self, config: Config) -> None:
        Component.configure(config)
        declaration = AppBuilder().with_service(OrderService())
        Component.reset_shared_state()

        with pytest.raises(ValueError, match="as an instance by agent 'order'"):
            AgentGroup("finance", {"order": declaration}).assemble(config)

    def test_the_instance_refusal_points_at_the_class_form(self, config: Config) -> None:
        Component.configure(config)
        declaration = AppBuilder().with_service(OrderService())
        Component.reset_shared_state()

        with pytest.raises(ValueError, match=r"with_service\(OrderService, \.\.\.\)"):
            AgentGroup("finance", {"order": declaration}).assemble(config)

    def test_a_factory_is_accepted(self, config: Config) -> None:
        """The capability the instance refusal costs nothing, because this recovers it."""
        declaration = AppBuilder().with_service(lambda: OrderService())

        AgentGroup("finance", {"order": declaration}).assemble(config)

        assert service_names() == ["order_order_service"]

    def test_nothing_is_assembled_when_a_refusal_fires(self, config: Config) -> None:
        """The refusals run before any replay, so a bad group leaves no half-built registry."""
        group = AgentGroup("finance", {"order": order_declaration, "billing": AppBuilder(config)})

        with pytest.raises(ValueError):
            group.assemble(config)

        assert service_names() == []


class TestTheGroupsCaches:
    """A group declares no caches: every cache belongs to the agent that declared it (D3)."""

    def test_a_group_cannot_declare_a_cache(self) -> None:
        """There is no process-wide cache, so there is no argument for naming one."""
        with pytest.raises(TypeError):
            AgentGroup("finance", {"order": order_declaration}, cache_names=("sessions",))  # type: ignore[call-arg]

    def test_a_group_whose_agents_declare_none_registers_none(self, config: Config) -> None:
        AgentGroup("finance", {"order": order_declaration}).assemble(config)

        assert registry().cache_entries() == []

    def test_an_agents_own_cache_is_carried_over_and_belongs_to_it(self, config: Config, tmp_path: Path) -> None:
        """A with_cache() in an agent's declaration is replayed like everything else."""
        config.get_cache_config = lambda: CacheConfig(cache_dir=str(tmp_path / "cache"), backend="disk")  # type: ignore[method-assign]
        declaration = AppBuilder().with_service(OrderService).with_cache(name="sessions")

        AgentGroup("finance", {"order": declaration}).assemble(config)

        assert [(namespace, name) for namespace, name, _ in registry().cache_entries()] == [("order", "sessions")]
        assert registry().get_all_caches() == {}, "the root declared none, so the root has none"

    def test_two_agents_declaring_one_name_get_separate_stores(self, config: Config, tmp_path: Path) -> None:
        """The whole of D3: ``sessions`` in two agents is two caches, not one shared by accident."""
        config.get_cache_config = lambda: CacheConfig(cache_dir=str(tmp_path / "cache"), backend="disk")  # type: ignore[method-assign]
        order = AppBuilder().with_service(OrderService).with_cache(name="sessions")
        billing = AppBuilder().with_service(BillingService).with_cache(name="sessions")

        AgentGroup("finance", {"order": order, "billing": billing}).assemble(config)

        theirs = registry().get_cache("sessions", namespace="order")
        neighbours = registry().get_cache("sessions", namespace="billing")
        assert theirs is not neighbours
        assert theirs.cache_dir != neighbours.cache_dir  # type: ignore[attr-defined]

    def test_neither_agent_can_read_the_others_cache(self, config: Config, tmp_path: Path) -> None:
        config.get_cache_config = lambda: CacheConfig(cache_dir=str(tmp_path / "cache"), backend="disk")  # type: ignore[method-assign]
        order = AppBuilder().with_service(OrderService).with_cache(name="sessions")
        billing = AppBuilder().with_service(BillingService)

        AgentGroup("finance", {"order": order, "billing": billing}).assemble(config)

        with pytest.raises(ValueError, match="No cache registered as 'sessions' for agent 'billing'"):
            registry().for_namespace("billing").get_cache("sessions")

    def test_a_health_checker_is_carried_over(self, config: Config) -> None:
        """Recording it is what stops a group silently dropping an agent's readiness checks."""
        checker = MagicMock()
        declaration = AppBuilder().with_service(OrderService).with_health_checker("db", checker)

        with patch("blueprint.agents.app_builder.ActuatorApi") as actuator, patch("blueprint.agents.app_builder.FastAPI"):
            AgentGroup("finance", {"order": declaration}).assemble(config)

        entries = actuator.return_value.add_health_providers.call_args[0][0]
        assert [(entry.key, entry.checker) for entry in entries] == [("order.db", checker)]


class TestLoadingADeclaration:
    def test_a_missing_module_fails_a_critical_agent(self) -> None:
        group = GroupConfig(name="finance", agents=(AgentSpec(name="order", module="no.such.module:declaration"),))

        with pytest.raises(GroupConfigError, match="could not be loaded and is critical"):
            AgentGroup.from_config(group)

    def test_the_failure_names_the_agent_and_the_module(self) -> None:
        group = GroupConfig(name="finance", agents=(AgentSpec(name="order", module="no.such.module:declaration"),))

        with pytest.raises(GroupConfigError, match=r"'order'.*no\.such\.module"):
            AgentGroup.from_config(group)

    def test_a_missing_attribute_fails_a_critical_agent(self) -> None:
        with pytest.raises(GroupConfigError, match="has no attribute 'nope'"):
            AgentGroup.from_config(GroupConfig(name="finance", agents=(spec("order", "nope"),)))

    def test_an_attribute_that_is_not_a_builder_is_refused(self) -> None:
        with pytest.raises(GroupConfigError, match="is a str, not an AppBuilder"):
            AgentGroup.from_config(GroupConfig(name="finance", agents=(spec("order", "not_a_declaration"),)))

    @pytest.mark.parametrize("module", ["no_colon_at_all", ":declaration", "module.path:"])
    def test_a_malformed_declaration_path_is_refused(self, module: str) -> None:
        group = GroupConfig(name="finance", agents=(AgentSpec(name="order", module=module),))

        with pytest.raises(GroupConfigError, match="is not a valid declaration path"):
            AgentGroup.from_config(group)

    def test_a_non_critical_agent_is_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """The flag is the deployment saying it would rather run the rest."""
        group = GroupConfig(
            name="finance",
            agents=(
                AgentSpec(name="order", module="no.such.module:declaration", critical=False),
                spec("billing", "billing_declaration"),
            ),
        )

        with caplog.at_level("ERROR", logger="blueprint.agents.agent_group"):
            assembled = AgentGroup.from_config(group)

        assert list(assembled.agents) == ["billing"]
        assert "is not critical, so it is skipped" in caplog.text

    def test_a_skipped_agent_does_not_stop_the_ones_after_it(self, config: Config) -> None:
        group = GroupConfig(
            name="finance",
            agents=(
                AgentSpec(name="order", module="no.such.module:declaration", critical=False),
                spec("billing", "billing_declaration"),
            ),
        )

        AgentGroup.from_config(group).assemble(config)

        assert service_names() == ["billing_billing_service"]

    def test_a_critical_agent_stops_resolution_before_later_ones(self, config: Config) -> None:
        """There is no partial build to unwind, so it fails rather than half-wiring the group."""
        group = GroupConfig(
            name="finance",
            agents=(AgentSpec(name="order", module="no.such.module:declaration"), spec("billing", "billing_declaration")),
        )

        with pytest.raises(GroupConfigError):
            AgentGroup.from_config(group)

        assert service_names() == []


class TestNoIoOfItsOwn:
    def test_from_config_reads_no_environment(self, config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        """The contract that keeps a group a pure function of the composition it was given."""
        monkeypatch.setenv("BLUEPRINT_AGENTS", "something-else")
        monkeypatch.setenv("BLUEPRINT_GROUP", "another-group")

        assembled = AgentGroup.from_config(GroupConfig(name="finance", agents=(spec("order", "order_declaration"),)))

        assert list(assembled.agents) == ["order"]

    def test_a_group_can_be_constructed_literally(self, config: Config) -> None:
        AgentGroup("finance", {"order": order_declaration}).assemble(config)

        assert service_names() == ["order_order_service"]


class TestResolve:
    def test_it_resolves_and_loads_in_one_call(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(f'[agents.order]\nmodule = "{_THIS}:order_declaration"\n')
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\napp_port = 8000\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        group = AgentGroup.resolve(config, environ={"BLUEPRINT_AGENTS": "order", "BLUEPRINT_GROUP": "finance"})

        assert group.name == "finance"
        assert list(group.agents) == ["order"]

    def test_a_resolution_failure_propagates(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\napp_port = 8000\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        with pytest.raises(GroupConfigError, match="No agent map at"):
            AgentGroup.resolve(config, environ={"BLUEPRINT_AGENTS": "order"})

    def test_it_returns_a_group_ready_to_assemble(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(f'[agents.order]\nmodule = "{_THIS}:order_declaration"\n')
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\napp_port = 8000\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        group: Any = AgentGroup.resolve(config, environ={"BLUEPRINT_AGENTS": "order"})

        assert isinstance(group, AgentGroup)


class TestTheBuilderKnowsNothingAboutGroups:
    def test_app_builder_has_no_group_methods(self) -> None:
        """Collection is the collector's job. An AppBuilder never learns it can be collected."""
        assert not hasattr(AppBuilder, "with_group")
        assert not hasattr(AppBuilder, "from_group")


def agent_settings(tmp_path: Path, body: str) -> Path:
    """Write an agent's own settings file into a directory of its own, and return the path.

    Not ``tmp_path`` itself: that is where the group's own settings file lives, and a fragment
    that *is* one of the process's settings files is skipped rather than merged a second time.
    """
    directory = tmp_path / "agent"
    directory.mkdir(exist_ok=True)
    path = directory / "settings.toml"
    path.write_text(f"{body}\n")
    return path


class ConfigReadingService(ServiceBase):
    """A service that reads its configuration where a project's own service would: at construction."""

    seen: dict[str, object] = {}

    def __init__(self) -> None:
        super().__init__()
        ConfigReadingService.seen[self.namespace] = self.config.get("model_name")

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class TestEachAgentsOwnSettings:
    """An agent's own ``settings.toml`` is merged under its scope at assembly (spec sec. 5.3, D5).

    What the merge itself does is pinned down in
    ``tests/unit/agents/config/test_agent_settings_fragments.py``; these cases are about the
    group -- where the file is looked for, and that it is merged early enough to be read.
    """

    def test_the_file_is_looked_for_beside_the_declaration_module(self) -> None:
        """One rule an author can see: the settings.toml in the agent's own directory."""
        group = GroupConfig(name="finance", agents=(AgentSpec(name="order", module=f"{_THIS}:order_declaration"),))

        resolved = AgentGroup.from_config(group)

        assert resolved.settings["order"] == Path(__file__).parent / "settings.toml"

    def test_an_agent_that_ships_none_is_simply_an_agent_without_settings(self, config: Config) -> None:
        """This test package has no settings.toml, so the path resolves to nothing to merge."""
        group = GroupConfig(name="finance", agents=(AgentSpec(name="order", module=f"{_THIS}:order_declaration"),))

        AgentGroup.from_config(group).assemble(config)

        assert service_names() == ["order_order_service"]

    def test_a_fragment_is_merged_under_its_agents_scope(self, config: Config, tmp_path: Path) -> None:
        fragment = agent_settings(tmp_path, 'model_name = "orders-own-model"')

        AgentGroup("finance", {"order": order_declaration}, settings={"order": fragment}).assemble(config)

        assert config.for_namespace("order").get("model_name") == "orders-own-model"

    def test_it_is_merged_before_the_agents_components_are_built(self, config: Config, tmp_path: Path) -> None:
        """A file merged after build() would have been read too late to matter."""
        ConfigReadingService.seen = {}
        fragment = agent_settings(tmp_path, 'model_name = "orders-own-model"')
        declaration = AppBuilder().with_service(ConfigReadingService)

        AgentGroup("finance", {"order": declaration}, settings={"order": fragment}).assemble(config)

        assert ConfigReadingService.seen == {"order": "orders-own-model"}

    def test_one_agents_file_does_not_reach_another(self, config: Config, tmp_path: Path) -> None:
        ConfigReadingService.seen = {}
        fragment = agent_settings(tmp_path, 'model_name = "orders-own-model"')
        order = AppBuilder().with_service(ConfigReadingService)
        billing = AppBuilder().with_service(BillingService)

        AgentGroup("finance", {"order": order, "billing": billing}, settings={"order": fragment}).assemble(config)

        assert config.for_namespace("billing").get("model_name") is None

    def test_a_group_that_was_given_none_merges_nothing(self, config: Config) -> None:
        group = AgentGroup("finance", {"order": order_declaration})

        group.assemble(config)

        assert group.settings == {}
