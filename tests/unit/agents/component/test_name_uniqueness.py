"""A registry name always says which agent it belongs to, and two components never share one.

The requirement is about reading logs, not about the registry. A component's registry name is
what appears in every log line, span and health entry, so two components that share one -- or one
whose name does not carry its agent -- cannot be told apart afterwards. Every way a name can be
set is covered here, because each of them used to be able to produce an ambiguous one.
"""

from pathlib import Path

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import namespace_scope, qualified_component_name
from blueprint.agents.config import Config
from blueprint.agents.services.service_base import ServiceBase


class Planner(ServiceBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class Reporter(ServiceBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class BillingHandler(ServiceBase):
    """A class whose snake_case name begins with a namespace's name. See the qualifier tests."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


@pytest.fixture
def config(tmp_path: Path) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[development]\napp_name = "root-app"\napp_port = 8000\n\n'
        '[development.orders]\napp_name = "orders"\n\n'
        '[development.billing]\napp_name = "billing"\n'
    )
    loaded = Config(settings_files=[str(settings)], root_path=str(tmp_path))
    Component.configure(loaded)
    return loaded


def registry_names() -> list[str]:
    registry = Component.shared_registry
    assert registry is not None
    return sorted(registry.get_component_names_by_type(Component))


class TestAnExplicitNameCarriesItsAgent:
    def test_a_directly_constructed_component_is_qualified(self, config: Config) -> None:
        """It used to be taken verbatim, so the log said 'planner' and not which agent's."""
        with namespace_scope("orders"):
            Planner(name="planner")

        assert registry_names() == ["orders_planner"]

    def test_two_agents_can_each_have_one(self, config: Config) -> None:
        with namespace_scope("orders"):
            orders = Planner(name="planner")
        with namespace_scope("billing"):
            billing = Planner(name="planner")

        assert registry_names() == ["billing_planner", "orders_planner"]
        assert (orders.name, billing.name) == ("orders_planner", "billing_planner")

    def test_the_root_keeps_the_bare_name(self, config: Config) -> None:
        Planner(name="planner")

        assert registry_names() == ["planner"]

    def test_a_rename_is_qualified_too(self, config: Config) -> None:
        with namespace_scope("orders"):
            planner = Planner()

        planner.name = "db"

        assert (planner.name, registry_names()) == ("orders_db", ["orders_db"])

    def test_a_rename_at_the_root_is_unchanged(self, config: Config) -> None:
        planner = Planner()

        planner.name = "db"

        assert planner.name == "db"


class TestTheQualifierDoesNotGuess:
    def test_a_base_name_starting_with_the_namespace_is_still_qualified(self, config: Config) -> None:
        """Skipping the prefix when it looks present would silently unqualify this component.

        ``BillingHandler`` in namespace ``billing`` derives ``billing_handler``, which *looks*
        qualified and is not. "Already prefixed" is not decidable from the string.
        """
        with namespace_scope("billing"):
            BillingHandler()

        assert registry_names() == ["billing_billing_handler"]

    def test_qualifying_is_a_plain_prefix(self, config: Config) -> None:
        assert qualified_component_name("orders", "db") == "orders_db"
        assert qualified_component_name("", "db") == "db"


class TestADuplicateNameFailsAtStartup:
    def test_two_components_of_one_class_in_one_agent_collide(self, config: Config) -> None:
        with namespace_scope("orders"):
            Planner()
            with pytest.raises(ValueError, match="is already taken by a Planner"):
                Planner()

    def test_two_explicit_names_that_collide_are_refused(self, config: Config) -> None:
        with namespace_scope("orders"):
            Planner(name="shared")
            with pytest.raises(ValueError, match="already taken"):
                Reporter(name="shared")

    def test_the_refusal_names_the_agent_and_the_fix(self, config: Config) -> None:
        with namespace_scope("orders"):
            Planner(name="shared")
            with pytest.raises(ValueError, match=r"namespace 'orders'.*distinct 'name='"):
                Reporter(name="shared")

    def test_a_root_component_and_an_agents_do_not_collide(self, config: Config) -> None:
        Planner(name="planner")
        with namespace_scope("orders"):
            Planner(name="planner")

        assert registry_names() == ["orders_planner", "planner"]


class TestARenameNeverLosesAComponent:
    def test_renaming_onto_a_taken_name_is_refused(self, config: Config) -> None:
        """This used to overwrite the dict entry, removing the other component silently."""
        planner = Planner(name="planner")
        Reporter(name="reporter")

        with pytest.raises(ValueError, match="already taken by a Reporter"):
            planner.name = "reporter"

    def test_the_other_component_is_still_registered_afterwards(self, config: Config) -> None:
        planner = Planner(name="planner")
        reporter = Reporter(name="reporter")

        with pytest.raises(ValueError):
            planner.name = "reporter"

        registry = Component.shared_registry
        assert registry is not None
        assert registry.get_component("reporter") is reporter
        assert registry.get_component("planner") is planner

    def test_renaming_to_the_same_name_is_a_no_op(self, config: Config) -> None:
        planner = Planner(name="planner")

        planner.name = "planner"

        assert registry_names() == ["planner"]

    def test_renaming_to_its_own_qualified_name_is_a_no_op(self, config: Config) -> None:
        """The setter qualifies, so assigning the bare name a component already has must settle."""
        with namespace_scope("orders"):
            planner = Planner(name="planner")

        planner.name = "planner"

        assert (planner.name, registry_names()) == ("orders_planner", ["orders_planner"])

    def test_renaming_an_unregistered_name_still_raises(self, config: Config) -> None:
        planner = Planner(name="planner")
        planner._name = "never-registered"

        with pytest.raises(ValueError, match="does not exist"):
            planner.name = "something"


class TestBaseName:
    """The unqualified half of a name, kept because it cannot be recovered from the qualified one."""

    def test_it_is_the_derived_name_at_the_root(self, config: Config) -> None:
        planner = Planner()
        assert (planner.name, planner.base_name) == ("planner", "planner")

    def test_it_drops_the_namespace(self, config: Config) -> None:
        with namespace_scope("orders"):
            planner = Planner()
        assert (planner.name, planner.base_name) == ("orders_planner", "planner")

    def test_an_explicit_name_is_kept_unqualified(self, config: Config) -> None:
        with namespace_scope("orders"):
            planner = Planner(name="scheduler")
        assert (planner.name, planner.base_name) == ("orders_scheduler", "scheduler")

    def test_it_follows_a_rename(self, config: Config) -> None:
        with namespace_scope("orders"):
            planner = Planner()
        planner.name = "scheduler"
        assert (planner.name, planner.base_name) == ("orders_scheduler", "scheduler")

    def test_a_base_name_starting_with_its_namespace_is_not_stripped(self, config: Config) -> None:
        """``qualified_component_name`` is not idempotent, which is why the half is stored."""
        with namespace_scope("billing"):
            handler = BillingHandler()
        assert (handler.name, handler.base_name) == ("billing_billing_handler", "billing_handler")
