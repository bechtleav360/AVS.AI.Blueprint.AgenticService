"""``asbs create`` rewrites main.py, and main.py changed shape.

A scaffolded ``main.py`` now assigns an unbuilt builder -- ``agent = (AppBuilder()...)`` with no
``build()`` call -- while a project written before that still ends its chain with ``.build()``.
The editor has to handle both, and the failure mode if it does not is silent: the registration
is appended to the end of the file, or the chain's lines are dropped while being re-sorted.
"""

from blueprint.agent_generator.cli.utils.naming_utils import (
    add_component_registration_to_main,
    extract_component_registrations,
    insert_before_declaration,
)

DECLARATION = '''"""A declaration."""

from blueprint.agents.app_builder import AppBuilder

from .services import OrderService

agent = (
    AppBuilder()
    .with_service(OrderService)
)
'''

LEGACY = '''"""An application that serves itself."""

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config

from .services import OrderService

config = Config(settings_files=["settings.toml"])

app = (
    AppBuilder(config=config)
    .with_service(OrderService())
    .build()
)
'''


class TestFindingTheChain:
    def test_a_declaration_closes_at_the_unindented_parenthesis(self) -> None:
        components, start, end = extract_component_registrations(DECLARATION)

        lines = DECLARATION.split("\n")
        assert components == [("service", "    .with_service(OrderService)")]
        assert lines[start].strip() == "AppBuilder()"
        assert lines[end] == ")"

    def test_an_application_still_closes_at_build(self) -> None:
        _, start, end = extract_component_registrations(LEGACY)

        lines = LEGACY.split("\n")
        assert lines[start].strip() == "AppBuilder(config=config)"
        assert lines[end].strip() == ".build()"

    def test_a_file_with_no_builder_reports_that_rather_than_guessing(self) -> None:
        components, start, end = extract_component_registrations("x = 1\n")

        assert (components, start, end) == ([], -1, -1)


class TestAddingARegistration:
    def test_it_lands_inside_the_declaration_chain(self) -> None:
        updated = add_component_registration_to_main(DECLARATION, "OrderPlacedHandler", "handler")

        assert updated.split("\n")[6:10] == [
            "agent = (",
            "    AppBuilder()",
            "    .with_service(OrderService)",
            "    .with_handler(OrderPlacedHandler)",
        ]
        assert updated.endswith(")\n")

    def test_it_registers_the_class_not_an_instance(self) -> None:
        """An already-built instance is refused when the agent is hosted in a group."""
        updated = add_component_registration_to_main(DECLARATION, "OrderApi", "api")

        assert "    .with_rest_api(OrderApi)" in updated
        assert "OrderApi()" not in updated

    def test_the_chain_is_ordered_by_dependency(self) -> None:
        updated = add_component_registration_to_main(DECLARATION, "OrderApi", "api")
        updated = add_component_registration_to_main(updated, "OrderPlacedHandler", "handler")

        chain = [line for line in updated.split("\n") if line.startswith("    .with_")]
        assert chain == [
            "    .with_service(OrderService)",
            "    .with_handler(OrderPlacedHandler)",
            "    .with_rest_api(OrderApi)",
        ]

    def test_an_application_that_serves_itself_keeps_its_build_call(self) -> None:
        updated = add_component_registration_to_main(LEGACY, "OrderPlacedHandler", "handler")

        assert "    .with_handler(OrderPlacedHandler)" in updated
        assert updated.index(".with_handler") < updated.index(".build()")


class TestInsertingADeclarationAbove:
    def test_it_goes_above_the_builder_whatever_the_variable_is_called(self) -> None:
        block = 'auditor_agent = (\n    AgentBuilder(runtime_name="auditor_agent")\n)\n'

        for source, variable in ((DECLARATION, "agent = ("), (LEGACY, "app = (")):
            updated = insert_before_declaration(source, block)

            assert updated.index(block) < updated.index(variable), (
                f"The declaration was not inserted above `{variable}`. Anchoring on the variable's name is what this "
                "replaces: it hard coded `app = (`, so a new agent's declaration silently went missing and the "
                "registration referred to a name that did not exist."
            )

    def test_a_file_with_no_builder_is_returned_unchanged(self) -> None:
        assert insert_before_declaration("x = 1\n", "block\n") == "x = 1\n"
