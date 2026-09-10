"""Applying a resolved group: one namespace per agent, and the group's caches.

``with_group`` is the wiring half of phase 8, and its contract is that it performs no I/O -- no
environment, no files, no ``sys.exit``, no knowledge of an agent repo's layout. That is why the
``GroupConfig`` here is always constructed literally: these tests state exact compositions
without arranging anything around the code under test.

Importing an agent's module is the one thing it reaches outside for, and it is driven entirely by
the ``module`` strings the group carries -- so the declarations below live in this file and are
named by their real dotted paths.
"""

from pathlib import Path
from typing import Any

import pytest

from blueprint.agents.app_builder import AgentRegistration, AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import DEFAULT_CACHE_NAME
from blueprint.agents.config import Config
from blueprint.agents.group_config import AgentSpec, GroupConfig, GroupConfigError
from blueprint.agents.models.config import CacheConfig
from blueprint.agents.services.service_base import ServiceBase

from .conftest import realize

_THIS = "tests.unit.agents.app_builder.test_with_group"


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
# module would expose them.
order_registration = AgentRegistration().with_service(OrderService)
billing_registration = AgentRegistration().with_service(BillingService)
not_a_registration = "this is not an AgentRegistration"


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


class TestOneNamespacePerAgent:
    def test_each_agent_is_applied_under_its_own_name(self, config: Config) -> None:
        group = GroupConfig(name="finance", agents=(spec("order", "order_registration"), spec("billing", "billing_registration")))

        realize(AppBuilder(config).with_group(group))

        assert component_names() == ["billing_billing_service", "order_order_service"]

    def test_the_builder_records_the_agents_it_hosts(self, config: Config) -> None:
        group = GroupConfig(name="finance", agents=(spec("order", "order_registration"), spec("billing", "billing_registration")))

        builder = AppBuilder(config).with_group(group)

        assert builder.namespaces == ("order", "billing")

    def test_declaration_order_is_kept(self, config: Config) -> None:
        group = GroupConfig(name="finance", agents=(spec("billing", "billing_registration"), spec("order", "order_registration")))

        builder = AppBuilder(config).with_group(group)

        assert builder.namespaces == ("billing", "order")

    def test_it_returns_the_builder(self, config: Config) -> None:
        builder = AppBuilder(config)

        assert builder.with_group(GroupConfig(name="empty", agents=())) is builder

    def test_a_group_of_one_is_an_ordinary_group(self, config: Config) -> None:
        """Group size 1 is how an agent gets a process to itself; nothing about it is special."""
        group = GroupConfig(name="just-order", agents=(spec("order", "order_registration"),))

        realize(AppBuilder(config).with_group(group))

        assert component_names() == ["order_order_service"]

    def test_the_same_declaration_can_serve_two_agents(self, config: Config) -> None:
        """One declaration, applied per agent -- the property the whole design rests on."""
        group = GroupConfig(name="two", agents=(spec("order", "order_registration"), spec("billing", "order_registration")))

        realize(AppBuilder(config).with_group(group))

        assert component_names() == ["billing_order_service", "order_order_service"]


class TestTheGroupsCaches:
    def test_declared_caches_are_registered(self, config: Config, tmp_path: Path) -> None:
        """A cache is process-wide, so the group declares it rather than any single agent."""
        config.get_cache_config = lambda: CacheConfig(cache_dir=str(tmp_path / "cache"), backend="disk")  # type: ignore[method-assign]
        group = GroupConfig(name="finance", agents=(spec("order", "order_registration"),), cache_names=("sessions", "prompts"))

        realize(AppBuilder(config).with_group(group))

        registry = Component.shared_registry
        assert registry is not None
        assert sorted(registry.get_all_caches()) == ["prompts", "sessions"]

    def test_a_group_with_no_caches_registers_none(self, config: Config) -> None:
        realize(AppBuilder(config).with_group(GroupConfig(name="finance", agents=(spec("order", "order_registration"),))))

        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_all_caches() == {}

    def test_the_default_cache_is_still_the_applications_to_add(self, config: Config, tmp_path: Path) -> None:
        """with_cache() on the chain and the group's list compose."""
        config.get_cache_config = lambda: CacheConfig(cache_dir=str(tmp_path / "cache"), backend="disk")  # type: ignore[method-assign]
        group = GroupConfig(name="finance", agents=(), cache_names=("sessions",))

        realize(AppBuilder(config).with_cache().with_group(group))

        registry = Component.shared_registry
        assert registry is not None
        assert sorted(registry.get_all_caches()) == [DEFAULT_CACHE_NAME, "sessions"]


class TestLoadingADeclaration:
    def test_a_missing_module_fails_a_critical_agent(self, config: Config) -> None:
        group = GroupConfig(name="finance", agents=(AgentSpec(name="order", module="no.such.module:registration"),))

        with pytest.raises(GroupConfigError, match="could not be loaded and is critical"):
            AppBuilder(config).with_group(group)

    def test_the_failure_names_the_agent_and_the_module(self, config: Config) -> None:
        group = GroupConfig(name="finance", agents=(AgentSpec(name="order", module="no.such.module:registration"),))

        with pytest.raises(GroupConfigError, match=r"'order'.*no\.such\.module"):
            AppBuilder(config).with_group(group)

    def test_a_missing_attribute_fails_a_critical_agent(self, config: Config) -> None:
        group = GroupConfig(name="finance", agents=(spec("order", "nope"),))

        with pytest.raises(GroupConfigError, match="has no attribute 'nope'"):
            AppBuilder(config).with_group(group)

    def test_an_attribute_that_is_not_a_registration_is_refused(self, config: Config) -> None:
        group = GroupConfig(name="finance", agents=(spec("order", "not_a_registration"),))

        with pytest.raises(GroupConfigError, match="is a str, not an AgentRegistration"):
            AppBuilder(config).with_group(group)

    @pytest.mark.parametrize("module", ["no_colon_at_all", ":registration", "module.path:"])
    def test_a_malformed_declaration_path_is_refused(self, config: Config, module: str) -> None:
        group = GroupConfig(name="finance", agents=(AgentSpec(name="order", module=module),))

        with pytest.raises(GroupConfigError, match="is not a valid declaration path"):
            AppBuilder(config).with_group(group)

    def test_a_non_critical_agent_is_skipped(self, config: Config, caplog: pytest.LogCaptureFixture) -> None:
        """The flag is the deployment saying it would rather run the rest."""
        group = GroupConfig(
            name="finance",
            agents=(
                AgentSpec(name="order", module="no.such.module:registration", critical=False),
                spec("billing", "billing_registration"),
            ),
        )

        with caplog.at_level("ERROR", logger="blueprint.agents.app_builder"):
            builder = AppBuilder(config).with_group(group)

        realize(builder)
        assert builder.namespaces == ("billing",)
        assert component_names() == ["billing_billing_service"]
        assert "is not critical, so it is skipped" in caplog.text

    def test_a_skipped_agent_does_not_stop_the_ones_after_it(self, config: Config) -> None:
        group = GroupConfig(
            name="finance",
            agents=(
                AgentSpec(name="order", module="no.such.module:registration", critical=False),
                spec("billing", "billing_registration"),
            ),
        )

        realize(AppBuilder(config).with_group(group))

        assert component_names() == ["billing_billing_service"]

    def test_a_critical_agent_stops_the_build_before_later_ones(self, config: Config) -> None:
        """There is no partial build to unwind, so it fails rather than half-wiring the group."""
        group = GroupConfig(
            name="finance",
            agents=(AgentSpec(name="order", module="no.such.module:registration"), spec("billing", "billing_registration")),
        )

        builder = AppBuilder(config)
        with pytest.raises(GroupConfigError):
            builder.with_group(group)

        realize(builder)
        assert "billing_billing_service" not in component_names()


class TestNoIoOfItsOwn:
    def test_it_reads_no_environment(self, config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        """The contract that keeps AppBuilder a pure function of its call sequence."""
        monkeypatch.setenv("BLUEPRINT_AGENTS", "something-else")
        monkeypatch.setenv("BLUEPRINT_GROUP", "another-group")
        group = GroupConfig(name="finance", agents=(spec("order", "order_registration"),))

        builder = AppBuilder(config).with_group(group)

        assert builder.namespaces == ("order",)

    def test_a_group_can_be_constructed_literally(self, config: Config) -> None:
        group = GroupConfig(name="finance", agents=(spec("order", "order_registration"),))

        realize(AppBuilder(config).with_group(group))

        assert component_names() == ["order_order_service"]


class TestFromGroup:
    def test_it_resolves_and_applies_in_one_call(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(f'[agents.order]\nmodule = "{_THIS}:order_registration"\n')
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\napp_port = 8000\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        builder = AppBuilder.from_group(config, environ={"BLUEPRINT_AGENTS": "order", "BLUEPRINT_GROUP": "finance"})

        realize(builder)
        assert builder.namespaces == ("order",)
        assert component_names() == ["order_order_service"]

    def test_a_resolution_failure_propagates(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\napp_port = 8000\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        with pytest.raises(GroupConfigError, match="No agent map at"):
            AppBuilder.from_group(config, environ={"BLUEPRINT_AGENTS": "order"})

    def test_it_returns_a_builder_ready_to_chain(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(f'[agents.order]\nmodule = "{_THIS}:order_registration"\n')
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\napp_port = 8000\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        builder: Any = AppBuilder.from_group(config, environ={"BLUEPRINT_AGENTS": "order"})

        assert isinstance(builder, AppBuilder)
