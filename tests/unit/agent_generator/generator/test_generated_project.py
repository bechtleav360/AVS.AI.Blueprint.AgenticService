"""What ``asbs setup`` produces, asserted against the framework that has to host it.

The generator's output is invisible from the framework's own tests, so a project that no longer
matches the framework it generates against is a defect nothing reports. These tests close that:
the project is generated into a temporary directory, its declaration is **imported**, and what
comes back is checked against the same rules the framework holds itself to -- a declaration
records and constructs nothing, a name that leaves the process is a legal namespace, and the
image's command can find the declaration it is asked to run.
"""

import importlib
import json
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.setup import create_basic_config
from blueprint.agent_generator.generator.generator import AgentGenerator
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import validate_namespace

PROJECT_NAME = "InvoiceProcessor"
AGENT_NAMESPACE = "invoice_processor"


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate the project ``asbs setup InvoiceProcessor`` produces, once for the module."""
    output = tmp_path_factory.mktemp("generated")
    config_file = output / "generator-config.json"
    config_file.write_text(json.dumps(create_basic_config(PROJECT_NAME)), encoding="utf-8")

    generator = AgentGenerator(str(config_file), str(output))
    generator.load_config()
    generator.generate()
    return output


@contextmanager
def declaration_of(project: Path) -> Iterator[AppBuilder]:
    """Import the generated ``src.main`` and yield the ``agent`` it declares.

    Imported rather than read as text, because the claim under test is that the framework can
    host this file -- and a file that parses is not the same as one whose imports resolve and
    whose builder calls exist. ``src`` is put back exactly as it was afterwards: the repository
    has a directory of that name too, and leaving the generated one in ``sys.modules`` would
    decide what a later test imports.
    """
    saved_path = list(sys.path)
    saved_modules = {name: module for name, module in sys.modules.items() if name == "src" or name.startswith("src.")}
    for name in saved_modules:
        del sys.modules[name]

    sys.path.insert(0, str(project))
    try:
        yield importlib.import_module("src.main").agent
    finally:
        for name in [name for name in sys.modules if name == "src" or name.startswith("src.")]:
            del sys.modules[name]
        sys.modules.update(saved_modules)
        sys.path[:] = saved_path


class TestTheGeneratedDeclaration:
    """``src/main.py`` declares an agent and builds nothing."""

    def test_main_assigns_an_unbuilt_app_builder(self, project: Path) -> None:
        with declaration_of(project) as agent:
            assert isinstance(agent, AppBuilder)
            assert not agent.is_built, (
                "The generated main.py built its application on import. It must only declare one: the host decides "
                "the configuration and the namespace, and a builder that has already run has taken both itself."
            )

    def test_importing_it_constructs_nothing(self, project: Path) -> None:
        """Collect, then wire -- asserted where it is easiest to break, in generated code."""
        before = dict(Component.shared_registry._components) if Component.shared_registry is not None else {}

        with declaration_of(project):
            after = dict(Component.shared_registry._components) if Component.shared_registry is not None else {}

        assert after == before, (
            "Importing the generated main.py put components in the registry. A component constructed while a "
            "declaration is still being collected exists before any namespace does, so it belongs to the root for "
            "ever -- which is exactly what a grouped deployment must not do."
        )

    def test_every_component_is_declared_once(self, project: Path) -> None:
        with declaration_of(project) as agent:
            declared = [(entry.kind, getattr(entry.target, "__name__", type(entry.target).__name__)) for entry in agent.declarations]

        assert declared == [
            ("service", "InvoiceProcessorService"),
            ("agent", "AgentBuilder"),
            ("handler", "InvoiceProcessorHandler"),
            ("rest_api", "InvoiceProcessorApi"),
        ]

    def test_the_agent_runtime_is_named_so_services_can_resolve_it(self, project: Path) -> None:
        """The generated service does ``registry.get_agent("<runtime>")``, so the name must be set."""
        with declaration_of(project) as agent:
            runtimes = [entry for entry in agent.declarations if entry.kind == "agent"]

        assert [entry.name for entry in runtimes] == [f"{AGENT_NAMESPACE}_agent"]

    def test_components_are_declared_as_classes_not_instances(self, project: Path) -> None:
        """An instance is refused when the agent is hosted in a group, so the generator emits classes."""
        with declaration_of(project) as agent:
            constructed = [entry.kind for entry in agent.declarations if entry.is_built]

        assert not constructed, (
            f"The generated main.py passes already-built {constructed} to the builder. A component constructed on "
            "the with_* line belongs to the root namespace for ever, which is why a group refuses it."
        )

    def test_it_neither_loads_configuration_nor_serves_itself(self, project: Path) -> None:
        source = (project / "src" / "main.py").read_text(encoding="utf-8")

        assert "Config(" not in source, "main.py loads configuration; the host supplies it, scoped to this agent."
        assert ".build()" not in source, "main.py builds its application; the host builds it, inside this agent's namespace."


class TestTheAgentMap:
    """``agents.toml`` is how the image's command finds the declaration."""

    def test_it_names_the_agent_and_its_declaration(self, project: Path) -> None:
        document = tomllib.loads((project / "agents.toml").read_text(encoding="utf-8"))

        assert document["agents"] == {AGENT_NAMESPACE: {"module": "src.main:agent"}}

    def test_the_agent_name_is_a_legal_namespace(self, project: Path) -> None:
        """It becomes a queue group, a durable, a cache partition and a service.name."""
        document = tomllib.loads((project / "agents.toml").read_text(encoding="utf-8"))

        for name in document["agents"]:
            assert validate_namespace(name) == name

    def test_the_module_it_names_is_the_one_that_declares_the_agent(self, project: Path) -> None:
        """The map is only useful if it resolves, and it is written by hand from here on."""
        document = tomllib.loads((project / "agents.toml").read_text(encoding="utf-8"))
        module_path, _, attribute = document["agents"][AGENT_NAMESPACE]["module"].partition(":")

        saved_path = list(sys.path)
        saved_modules = {name: module for name, module in sys.modules.items() if name == "src" or name.startswith("src.")}
        for name in saved_modules:
            del sys.modules[name]
        sys.path.insert(0, str(project))
        try:
            module = importlib.import_module(module_path)
            assert isinstance(getattr(module, attribute), AppBuilder)
        finally:
            for name in [name for name in sys.modules if name == "src" or name.startswith("src.")]:
                del sys.modules[name]
            sys.modules.update(saved_modules)
            sys.path[:] = saved_path


class TestTheImage:
    """The Dockerfile runs the framework's entry point, and bakes no group."""

    def test_the_command_is_the_framework_entry_point(self, project: Path) -> None:
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        assert 'ENTRYPOINT ["python", "-m", "blueprint.agents.entrypoint"]' in dockerfile
        assert "uvicorn" not in dockerfile.split("FROM python:3.13-slim-bookworm AS final")[1], (
            "The production stage still serves an application object. Which agents the process hosts is resolved at "
            "container start, which uvicorn cannot do on its own."
        )

    def test_the_agent_map_is_in_the_image(self, project: Path) -> None:
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        assert "COPY --chown=appuser:appuser agents.toml ./" in dockerfile

    def test_no_group_is_baked_into_the_production_image(self, project: Path) -> None:
        """One image serves every group; the group arrives at container start."""
        final_stage = (project / "Dockerfile").read_text(encoding="utf-8").split("FROM python:3.13-slim-bookworm AS final")[1]

        assert "ENV BLUEPRINT_AGENTS" not in final_stage
        assert "BLUEPRINT_GROUP" not in final_stage.replace("BLUEPRINT_GROUP=<group>", "")

    def test_the_documented_run_command_names_the_real_agent(self, project: Path) -> None:
        """A placeholder here is a command that looks runnable and is not."""
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        assert f"docker run -e BLUEPRINT_AGENTS={AGENT_NAMESPACE} <image>" in dockerfile
        assert "agent_namespace" not in dockerfile


class TestAnUnusableProjectNameIsRefused:
    """A name that cannot be a namespace fails the generator rather than the deployment."""

    def test_a_leading_digit_is_refused_with_the_reason(self) -> None:
        from blueprint.agent_generator.generator.part_generators import AgentMapPartGenerator

        with pytest.raises(ValueError, match="cannot be used"):
            AgentMapPartGenerator.agent_namespace({"name": "2ndAgent"})
