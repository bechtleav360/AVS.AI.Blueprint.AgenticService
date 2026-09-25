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
import re
import shutil
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI

from blueprint.agent_generator.cli.commands.setup import create_basic_config
from blueprint.agent_generator.generator.generator import AgentGenerator
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.component.namespace import validate_namespace
from blueprint.agents.config import Config
from blueprint.agents.config.config import DEFAULT_SETTINGS_FILES
from blueprint.agents.entrypoint import build_group_app

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

    def test_the_declaration_itself_neither_configures_nor_builds(self, project: Path) -> None:
        """The chain records; only create_app() builds, and only when serving this agent alone.

        A group never calls create_app: it builds the same declaration itself, inside the agent's
        namespace. So nothing above create_app may mention configuration or build anything.
        """
        source = (project / "src" / "main.py").read_text(encoding="utf-8")
        declaration = source.split("def create_app()")[0]

        assert "Config(" not in declaration, "the declaration loads configuration; its host supplies that"
        assert ".build(" not in declaration, "the declaration builds itself; its host builds it, in its own namespace"

    def test_it_can_serve_itself_without_a_group(self, project: Path) -> None:
        """create_app is the standalone path, and it is the only place configuration appears."""
        source = (project / "src" / "main.py").read_text(encoding="utf-8")

        assert "def create_app()" in source
        assert "agent.build(" in source
        code = source.split('"""', 2)[-1]
        assert "agents.toml" not in code, "the declaration reads an agent map; a standalone agent has none"


class TestTheAgentMap:
    """A scaffolded agent has no agent map, and its own image does not write one either.

    The map says which agents an *image* contains, which is a packaging decision. An agent
    served on its own contains no group at all -- a group of one is still a group, and an agent
    must not have to declare itself one to run alone.
    """

    def test_the_agent_does_not_carry_one(self, project: Path) -> None:
        assert not (project / "agents.toml").exists()

    def test_its_own_image_does_not_write_one(self, project: Path) -> None:
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        assert "agents.toml" not in dockerfile.replace("# agents.toml names this module", "")
        assert "BLUEPRINT_AGENTS" not in dockerfile.replace("BLUEPRINT_* variable", "")

    def test_it_is_served_through_its_own_factory(self, project: Path) -> None:
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        assert "src.main:create_app" in dockerfile
        assert "blueprint.agents.entrypoint" not in dockerfile

    def test_the_agent_name_is_a_legal_namespace(self, project: Path) -> None:
        """Whoever hosts it uses this name; it becomes a queue group, durable and service.name."""
        for name in (AGENT_NAMESPACE,):
            assert validate_namespace(name) == name

    def test_the_module_it_names_is_the_one_that_declares_the_agent(self, project: Path) -> None:
        """The map is only useful if it resolves, and it is written by hand from here on."""
        module_path, _, attribute = "src.main:agent".partition(":")

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


class TestWhatTheProjectShips:
    """Files the project needs that are not code."""

    def test_the_secrets_file_and_its_template_land_in_the_project(self, project: Path) -> None:
        """create_file() with no argument writes relative to the working directory, so the
        secrets file used to be left wherever `asbs setup` was run from."""
        assert (project / ".secrets.toml").is_file()
        assert (project / ".secrets.toml.example").is_file()

    def test_the_secrets_file_is_the_one_the_framework_loads(self, project: Path) -> None:
        """The name is the whole of it. `DEFAULT_SETTINGS_FILES` is what `entrypoint.py` hands to
        `Config`, so a file called anything else is loaded by nothing and reports nothing."""
        assert ".secrets.toml" in DEFAULT_SETTINGS_FILES
        assert not (project / "secrets.toml").exists()

    def test_the_project_configures_itself_from_the_files_the_image_reads(self, project: Path) -> None:
        """The regression this closes: `asbs setup` produced a project that could not start.
        Its `model_provider = "vllm"` makes the API key a validated requirement, and the key is
        in the secrets file, so an unloaded secrets file was a `ConfigError` on an unedited
        project rather than a missing value somewhere later."""
        config = Config(settings_files=DEFAULT_SETTINGS_FILES, root_path=str(project))

        assert config.get_ai_config().api_key

    def test_it_ships_the_tests_directory_its_own_validator_requires(self, project: Path) -> None:
        """`asbs validate` requires `tests/`, so a scaffolded project used to fail the validation
        of the tool that made it."""
        assert (project / "tests" / "test_declaration.py").is_file()
        assert (project / "tests" / "test_mapper.py").is_file()

    def test_a_pyproject_is_written_when_the_directory_has_none(self, project: Path) -> None:
        """`asbs validate` requires one, and a directory with no pyproject has nothing to lose."""
        document = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))

        assert document["project"]["name"]
        assert "avs-blueprint-agents" in document["project"]["dependencies"]

    def test_an_existing_pyproject_is_left_alone(self, tmp_path: Path) -> None:
        """`asbs` is installed into the project's own environment, so by the time it can run
        there is usually a pyproject already -- somebody's, with their dependencies in it.
        Writing over it would be this tool destroying the file that made it runnable."""
        theirs = '[project]\nname = "already-here"\nversion = "9.9.9"\n'
        (tmp_path / "pyproject.toml").write_text(theirs, encoding="utf-8")
        config_file = tmp_path / "generator-config.json"
        config_file.write_text(json.dumps(create_basic_config(PROJECT_NAME)), encoding="utf-8")

        generator = AgentGenerator(str(config_file), str(tmp_path))
        generator.load_config()
        generator.generate()

        assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == theirs

    def test_the_tests_import_the_declaration_without_any_pytest_configuration(self, project: Path) -> None:
        """`test_declaration.py` imports `src.main` -- what `agents.toml` names and what the
        entry point imports -- so the project root has to be importable. `tests/conftest.py` does
        that itself rather than relying on a `pythonpath` setting in somebody else's pyproject.
        """
        conftest = (project / "tests" / "conftest.py").read_text(encoding="utf-8")

        assert "sys.path.insert" in conftest
        assert "PROJECT_ROOT" in conftest

    def test_the_secrets_file_is_git_ignored_and_the_template_is_not(self, project: Path) -> None:
        """Read as patterns rather than as text: a comment naming the example file would
        otherwise pass for a rule ignoring it, in either direction."""
        patterns = [line.strip() for line in (project / ".gitignore").read_text(encoding="utf-8").splitlines() if line.strip()]
        patterns = [line for line in patterns if not line.startswith("#")]

        assert "**/.secrets.toml" in patterns
        assert not [line for line in patterns if line.endswith(".example") or line.endswith(".secrets.*")]


class TestTheGeneratedSettingsAreRead:
    """Every key the scaffolded ``settings.toml`` writes is a key the framework looks up.

    A settings file is the one place a developer expects to be believed, and a key in the wrong
    shape fails silently in both directions: nothing reads it, and nothing says so. These tests
    load the generated file through a real ``Config`` and assert the value in the file is the
    value that comes back -- flipping each one first, so what is asserted is that the key is
    live rather than that its value happens to match the framework's default.
    """

    @staticmethod
    def _loaded(project: Path, tmp_path: Path, **overrides: str) -> Config:
        """Load the generated settings file, with the named keys rewritten to new values.

        The generated ``secrets.toml`` is loaded alongside it and named explicitly, because the
        scaffolded ``model_provider = "vllm"`` makes the API key a validated requirement.
        """
        body = (project / "settings.toml").read_text(encoding="utf-8")
        for key, value in overrides.items():
            replaced = re.subn(rf"^{key} = .*$", f"{key} = {value}", body, count=1, flags=re.MULTILINE)
            assert replaced[1] == 1, f"the generated settings.toml no longer writes a top-level '{key}'"
            body = replaced[0]

        (tmp_path / "settings.toml").write_text(body, encoding="utf-8")
        (tmp_path / ".secrets.toml").write_text((project / ".secrets.toml").read_text(encoding="utf-8"), encoding="utf-8")
        return Config(settings_files=DEFAULT_SETTINGS_FILES, root_path=str(tmp_path))

    def test_telemetry_turns_on_from_the_file(self, project: Path, tmp_path: Path) -> None:
        """Under ``[default.observability]`` this was inert: the file said true and read False."""
        config = self._loaded(project, tmp_path, otel_enabled="true")

        assert config.get_observability_config().otel_enabled is True

    def test_token_metrics_turn_off_from_the_file(self, project: Path, tmp_path: Path) -> None:
        config = self._loaded(project, tmp_path, token_metrics_enabled="false")

        assert config.get_observability_config().token_metrics_enabled is False

    def test_the_process_wide_logging_keys_are_left_commented_out(self, project: Path) -> None:
        """They describe the process, not this agent.

        In a group they are dropped before the merge with a warning, so a scaffolded agent that
        set them would make every group it joined complain about a file the scaffolder wrote.
        Commented out rather than absent, because a single-agent deployment does want them and
        the agent's directory is the image there.
        """
        body = (project / "settings.toml").read_text(encoding="utf-8")

        assert "# log_level = " in body
        assert "# log_format = " in body

    def test_no_table_is_written_that_nothing_reads(self, project: Path) -> None:
        """The framework reads these four flat. A section of the same name is dead weight that
        reads as configuration."""
        default = tomllib.loads((project / "settings.toml").read_text(encoding="utf-8"))["default"]

        assert "logging" not in default
        assert "observability" not in default


class TestTheProjectTheEntryPointBuilds:
    """`asbs setup` produces a project that `python -m blueprint.agents.entrypoint` can run.

    Every other test here reads the declaration; this one builds it, through the same function
    the container's command calls. That is the only way this class of defect surfaces: the
    declaration was always well-formed, and what failed was the construction of what it
    declared. Nothing is started -- the lifespan is where an agent reaches for its model -- so
    this asserts assembly, not a working LLM.
    """

    @pytest.fixture
    def built(self, project: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
        """Build the group the entry point would, with the project as the working directory.

        `Config` resolves `settings.toml` and `.secrets.toml` relative to the working directory
        and the agent's prompts relative to `prompt_directory`, so the chdir is what the
        container does by having WORKDIR /app. The registry is process-global, hence the reset.
        """
        saved_path = list(sys.path)
        saved_modules = {
            name: module for name, module in sys.modules.items() if name in ("src", "agents") or name.startswith(("src.", "agents."))
        }
        for name in saved_modules:
            del sys.modules[name]

        # A real image: the agents live in subdirectories and the map sits beside them. The
        # agent directory is copied verbatim, which is the claim -- nothing in it changes to
        # be hosted by a group.
        image = project.parent / "image"
        if image.exists():
            shutil.rmtree(image)
        (image / "agents").mkdir(parents=True)
        shutil.copytree(project, image / "agents" / AGENT_NAMESPACE)
        (image / "agents.toml").write_text(
            f'[agents.{AGENT_NAMESPACE}]{chr(10)}root   = "agents/{AGENT_NAMESPACE}"{chr(10)}'
            f'module = "agents.{AGENT_NAMESPACE}.src.main:agent"{chr(10)}',
            encoding="utf-8",
        )
        (image / "settings.toml").write_text((project / "settings.toml").read_text(encoding="utf-8"), encoding="utf-8")
        (image / ".secrets.toml").write_text((project / ".secrets.toml").read_text(encoding="utf-8"), encoding="utf-8")

        monkeypatch.chdir(image)
        sys.path.insert(0, str(image))
        try:
            app, _ = build_group_app(environ={"BLUEPRINT_AGENTS": AGENT_NAMESPACE, "BLUEPRINT_GROUP": "test"})
            yield app
        finally:
            Component.reset_shared_state()
            shutil.rmtree(image, ignore_errors=True)
            for name in [n for n in sys.modules if n in ("src", "agents") or n.startswith(("src.", "agents."))]:
                del sys.modules[name]
            sys.modules.update(saved_modules)
            sys.path[:] = saved_path

    def test_the_group_assembles(self, built: FastAPI) -> None:
        """`AgentBuilder.build()` constructed `AgentRuntime` without the name it requires, so
        this raised `TypeError` -- for every scaffolded project, and for any group at all."""
        assert isinstance(built, FastAPI)

    def test_the_agents_components_are_registered_under_its_namespace(self, built: FastAPI) -> None:
        registry = Component.shared_registry
        assert registry is not None
        names = registry.get_component_names_by_type(Component, AGENT_NAMESPACE)

        assert names, "the agent was assembled with no components of its own"
        assert all(name.startswith(f"{AGENT_NAMESPACE}_") for name in names), names


class TestEverythingWrittenIsAscii:
    """What the CLI prints may be UTF-8; what it writes may not.

    The repository's rule is ASCII in source, and a scaffolded project is source somebody else
    then owns -- so an em-dash or a check mark the generator emitted would be a rule violation
    the recipient inherits and did not choose. This is also the half of the console fix that has
    to be held in place: `use_utf8` makes the CLI's *output* UTF-8, and nothing about that should
    reach a file.
    """

    @pytest.fixture
    def untouched(self, tmp_path: Path) -> Path:
        """A project generated for this test alone, and never run.

        Not the module's shared ``project``: other tests import ``src.main`` and build the group
        inside it, which leaves ``__pycache__`` behind -- and a ``.pyc`` is binary, so the check
        would fail on an artefact the generator never wrote. What is under test is what the
        generator emits, so it has to be looked at before anything else has been there.
        """
        config_file = tmp_path / "generator-config.json"
        config_file.write_text(json.dumps(create_basic_config(PROJECT_NAME)), encoding="utf-8")

        generator = AgentGenerator(str(config_file), str(tmp_path))
        generator.load_config()
        generator.generate()
        return tmp_path

    def test_no_generated_file_contains_a_non_ascii_byte(self, untouched: Path) -> None:
        offenders: list[str] = []
        for path in sorted(untouched.rglob("*")):
            if not path.is_file() or path.name == "generator-config.json":
                continue
            try:
                path.read_text(encoding="ascii")
            except UnicodeDecodeError as decoded:
                offenders.append(f"{path.relative_to(untouched).as_posix()}: {decoded.reason} at byte {decoded.start}")

        assert offenders == [], "the generator wrote non-ASCII into: " + "; ".join(offenders)


class TestTheImage:
    """The Dockerfile runs the framework's entry point, and bakes no group."""

    def test_the_command_is_the_framework_entry_point(self, project: Path) -> None:
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        final = dockerfile.split("FROM python:3.13-slim-bookworm AS final")[1]

        assert "src.main:create_app" in final
        assert "--factory" in final, "create_app is a factory; uvicorn needs an import string to reload it"
        assert "blueprint.agents.entrypoint" not in final, (
            "The image serves one agent through the group entry point, which makes a standalone agent declare itself a group of one."
        )

    def test_no_agent_map_is_in_the_image(self, project: Path) -> None:
        """This image holds one agent and serves it; there is no group for a map to describe."""
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        assert "/app/agents.toml" not in dockerfile
        assert "COPY --chown=appuser:appuser agents.toml" not in dockerfile

    def test_no_group_is_baked_into_the_production_image(self, project: Path) -> None:
        """One image serves every group; the group arrives at container start."""
        final_stage = (project / "Dockerfile").read_text(encoding="utf-8").split("FROM python:3.13-slim-bookworm AS final")[1]

        assert "ENV BLUEPRINT_AGENTS" not in final_stage
        assert "BLUEPRINT_GROUP" not in final_stage.replace("BLUEPRINT_GROUP=<group>", "")

    def test_every_file_the_dockerfile_copies_is_generated(self, project: Path) -> None:
        """#11 -- it copied a README.md nothing generates, so a fresh `docker build` failed."""
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")
        sources = []
        for line in dockerfile.splitlines():
            words = line.split()
            if not words or words[0] != "COPY" or any(word.startswith("--from") for word in words):
                continue
            sources.extend(word for word in words[1:-1] if not word.startswith("--"))
        assert sources, "the Dockerfile copies nothing from the build context"
        missing = [source for source in sources if not (project / source).exists()]
        assert missing == []

    def test_the_documented_run_command_needs_no_group(self, project: Path) -> None:
        """A placeholder here is a command that looks runnable and is not."""
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        assert "docker run -p 8000:8000 <image>" in dockerfile
        assert "agent_namespace" not in dockerfile

    def test_the_healthcheck_names_a_route_the_application_serves(self, project: Path) -> None:
        """A HEALTHCHECK on a 404 does not report "unknown", it reports unhealthy, for ever.

        `ActuatorApi` serves `/health/live` and `/health/ready` and nothing at `/health`, so the
        bare path fails `curl -f` on every probe: the container never becomes healthy, compose's
        `depends_on: service_healthy` never releases, and an orchestrator reading Docker's own
        health state sees a permanently failing container that is in fact serving traffic.
        """
        dockerfile = (project / "Dockerfile").read_text(encoding="utf-8")

        assert "/health/live" in dockerfile
        assert "8000/health || exit 1" not in dockerfile, "the bare /health is not a route this application serves"


class TestAnUnusableProjectNameIsRefused:
    """A name that cannot be a namespace fails the generator rather than the deployment."""

    def test_a_leading_digit_is_refused_with_the_reason(self) -> None:
        from blueprint.agent_generator.generator.part_generators.part_generator_base import PartGeneratorBase

        with pytest.raises(ValueError, match="cannot be used"):
            PartGeneratorBase.agent_namespace({"name": "2ndAgent"})


class TestTheGeneratedSettings:
    """What settings.toml must not decide for the author, or bake in."""

    def test_no_scheduler_mode_is_chosen(self, project: Path) -> None:
        """It has no default by design; an active line in the template chose one anyway."""
        settings = (project / "settings.toml").read_text(encoding="utf-8")
        active = [line for line in settings.splitlines() if line.startswith("scheduler_mode")]
        assert active == []

    def test_no_internal_host_is_baked_in(self, project: Path) -> None:
        assert "q14.net" not in (project / "settings.toml").read_text(encoding="utf-8")


class TestAnInvalidGeneratorConfig:
    def test_it_raises_instead_of_exiting_the_interpreter(self, tmp_path: Path) -> None:
        """Library code: sys.exit took the decision away from every caller."""
        config_file = tmp_path / "generator-config.json"
        config_file.write_text(json.dumps({"name": "Incomplete"}), encoding="utf-8")
        generator = AgentGenerator(str(config_file), str(tmp_path / "out"))

        with pytest.raises(ValueError, match="is not valid"):
            generator.load_config()
