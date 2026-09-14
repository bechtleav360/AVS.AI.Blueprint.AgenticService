from pathlib import Path
from typing import Any

from .part_generator_base import PartGeneratorBase


class TestsPartGenerator(PartGeneratorBase):
    """Write the tests a scaffolded project starts with.

    **Two, and deliberately not more.** The scaffolded handler and service raise
    ``NotImplementedError`` in the methods that matter -- they are where the author's business
    logic goes -- so a generated test of ``handle_event`` could only assert that the stub is
    still a stub, and would fail the moment it stopped being one. A test that has to be deleted
    before the project can work is worse than no test: it teaches that the suite is noise.

    What is generated is the part that is true on day one and stays true:

    - **the declaration** -- ``src/main.py`` declares an unbuilt ``AppBuilder``, constructs
      nothing when imported, and passes classes rather than instances. This is the file an author
      edits most and the one whose mistakes are least visible: building it, or passing an
      instance, both work standalone and both make the project impossible to host in a group.
    - **the mapper** -- the one piece of generated code with real logic in it, so a round trip
      through it is a real assertion.

    ``asbs validate`` requires a ``tests/`` directory, and until now ``asbs setup`` did not write
    one, so a freshly scaffolded project failed its own validation.
    """

    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str, *, part: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = None
        self._part = part
        builders = {"declaration": self._declaration_test, "mapper": self._mapper_test, "conftest": self._conftest}
        self.template_vars["content"] = builders[part]()

    def to_py_file_name(self) -> str:
        return "conftest.py" if self._part == "conftest" else f"test_{self._part}.py"

    def _conftest(self) -> str:
        """Put the project root on the path, so the tests need no pytest configuration at all.

        ``test_declaration.py`` imports ``src.main`` -- the same import ``agents.toml`` names and
        the container entry point performs -- which needs the project root importable. That can
        come from ``pythonpath`` in ``pyproject.toml``, but a scaffolded project is scaffolded
        *into* a project that already exists and already has a ``pyproject.toml`` of its own, and
        editing somebody's build configuration to make generated tests run is not this tool's
        business. Doing it here costs four lines and depends on nothing.
        """
        return '''"""Make the project root importable, so `from src.main import agent` resolves.

`src.main` is what `agents.toml` names and what `python -m blueprint.agents.entrypoint` imports,
so the tests import it the same way the runtime does rather than a way of their own.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
'''

    def _declaration_test(self) -> str:
        """A test of what ``src/main.py`` declares, and of what it must not do on import."""
        name = self.config["name"]
        # service_layer is keyed by class name; the value describes it.
        components = [f'"{service}"' for service in self.config["service_layer"]]
        return f'''"""What ``src/main.py`` declares.

``main.py`` is a *declaration*: every ``with_*`` call records what this agent is made of, and
nothing is constructed until the host calls ``build()``. That is what lets this project run on
its own and be hosted alongside other agents in one process.

Both mistakes this guards against work fine standalone, which is why they are easy to make and
hard to notice: calling ``.build()`` in this file takes the configuration and the namespace that
the host is supposed to decide, and passing an already-constructed component
(``.with_service(MyService())`` instead of ``.with_service(MyService)``) creates it before any
namespace exists, so it belongs to the root for ever.
"""

from blueprint.agents.app_builder import AppBuilder

from src.main import agent


def test_main_declares_an_unbuilt_builder() -> None:
    assert isinstance(agent, AppBuilder)
    assert not agent.is_built, "main.py built the application on import; the host builds it"


def test_nothing_is_constructed_on_import() -> None:
    """A declaration records; it does not create. Instances here would carry the root namespace."""
    constructed = [declaration.kind for declaration in agent.declarations if declaration.is_built]

    assert not constructed, f"main.py passes already-built {{constructed}} to the builder; pass the class instead"


def test_every_component_is_declared() -> None:
    """Rename or remove a component and this is what tells you main.py was not updated."""
    kinds = [declaration.kind for declaration in agent.declarations]

    assert "service" in kinds
    assert "handler" in kinds


def test_the_services_this_project_ships_are_declared() -> None:
    declared = {{
        getattr(declaration.target, "__name__", type(declaration.target).__name__)
        for declaration in agent.declarations
        if declaration.kind == "service"
    }}

    assert declared == {{{", ".join(components)}}}, f"{name} declares {{declared}}"
'''

    def _mapper_test(self) -> str:
        """A round trip through the generated mapper, which is real code rather than a stub."""
        name = self.config["name"]
        snake = self.camel_to_snake(name)
        return f'''"""The mapper, which is the one piece of generated code with logic in it.

DTOs are what the REST API speaks; domain models are what the service works on. The mapper is
the boundary, and a round trip through it is the cheapest statement that the boundary is intact
-- if a field is added to one side and not the other, this is what says so.
"""

from src.models.{snake}.dto import {name}RequestDTO, {name}ResponseDTO
from src.models.{snake}.mapper import {name}Mapper


def test_a_request_becomes_a_domain_model() -> None:
    request = {name}RequestDTO(id="abc", data={{"key": "value"}})

    model = {name}Mapper.from_{snake}_request_dto(request)

    assert model.id == "abc"
    assert model.data == {{"key": "value"}}


def test_a_domain_model_becomes_a_response() -> None:
    model = {name}Mapper.from_{snake}_request_dto({name}RequestDTO(id="abc", data={{"key": "value"}}))

    response = {name}Mapper.to_{snake}_response_dto(model)

    assert isinstance(response, {name}ResponseDTO)
    assert (response.id, response.data) == ("abc", {{"key": "value"}})


def test_the_round_trip_changes_nothing() -> None:
    """What the test is really for: a field added on one side and forgotten on the other."""
    request = {name}RequestDTO(id="abc", data={{"key": "value"}})

    response = {name}Mapper.to_{snake}_response_dto({name}Mapper.from_{snake}_request_dto(request))

    assert response.model_dump() == request.model_dump()
'''
