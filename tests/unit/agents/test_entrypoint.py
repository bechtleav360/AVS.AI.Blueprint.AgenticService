"""The container's command: what it starts, and how it fails.

The failure path is the reason this module exists as its own unit. A group that cannot be
resolved has to stop the process *before the port is bound*, with a message an operator can act
on -- otherwise Kubernetes reports a healthy replica that is silently short a consumer, which is
the failure this whole feature is built to prevent.
"""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

from blueprint.agents import entrypoint
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from blueprint.agents.component.component import Component
from blueprint.agents.services.service_base import ServiceBase

_THIS = "tests.unit.agents.test_entrypoint"


class OrderService(ServiceBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


# What a project's main.py contains: an AppBuilder that has never been built.
order_declaration = AppBuilder().with_service(OrderService)


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    """Clear the process-wide component state around every case.

    ``build()`` runs a real ``AppBuilder.build()``, which injects the configuration once and
    registers components under process-wide names -- so without this the second case in the file
    fails on "Config is already set" or a duplicate registry name rather than on anything it
    was testing.
    """
    Component.reset_shared_state()
    yield
    Component.reset_shared_state()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project root the entry point will pick up, with the working directory moved into it.

    The entry point loads ``settings.toml`` relative to the working directory, because that is
    what the container's ``WORKDIR`` provides. So this fixture reproduces the container's shape
    rather than passing paths the real entry point has no parameter for.
    """
    (tmp_path / "agents.toml").write_text(f'[agents.order]\nmodule = "{_THIS}:order_declaration"\n')
    (tmp_path / "settings.toml").write_text('[development]\napp_environment = "development"\napp_name = "the-process"\napp_port = 8000\n')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def component_names() -> list[str]:
    registry = Component.shared_registry
    assert registry is not None
    return sorted(registry.get_component_names_by_type(Component))


class TestBuildGroupApp:
    def test_it_is_not_called_build(self) -> None:
        """AppBuilder.build() returns a FastAPI; a second 'build' returning a tuple misleads."""
        assert not hasattr(entrypoint, "build")

    def test_it_builds_the_group_the_environment_names(self, project: Path) -> None:
        app, config = entrypoint.build_group_app(environ={"BLUEPRINT_AGENTS": "order", "BLUEPRINT_GROUP": "finance"})

        assert app is not None
        assert config.get("app_name") == "the-process"
        assert "order_order_service" in component_names()

    def test_it_reads_the_group_file_when_there_is_one(self, project: Path) -> None:
        (project / "deployment-groups.yaml").write_text("groups:\n  - name: finance\n    agents: [order]\n")

        entrypoint.build_group_app(environ={})

        assert "order_order_service" in component_names()

    def test_a_resolution_failure_propagates(self, project: Path) -> None:
        """It raises; deciding what to do about it is main()'s job."""
        from blueprint.agents.group_config import GroupConfigError

        with pytest.raises(GroupConfigError):
            entrypoint.build_group_app(environ={"BLUEPRINT_AGENTS": "not-in-this-image"})


class TestMain:
    def test_it_serves_the_application(self, project: Path) -> None:
        with patch.object(entrypoint, "run_app") as run:
            status = entrypoint.main(environ={"BLUEPRINT_AGENTS": "order", "BLUEPRINT_GROUP": "finance"})

        assert status == 0
        run.assert_called_once()

    def test_the_application_it_serves_is_the_one_it_built(self, project: Path) -> None:
        with patch.object(entrypoint, "run_app") as run:
            entrypoint.main(environ={"BLUEPRINT_AGENTS": "order"})

        app, config = run.call_args[0]
        assert app is not None
        assert config.get("app_port") == 8000

    def test_a_bad_group_exits_non_zero(self, project: Path) -> None:
        with patch.object(entrypoint, "run_app") as run:
            status = entrypoint.main(environ={"BLUEPRINT_AGENTS": "not-in-this-image"})

        assert status == 1
        run.assert_not_called()

    def test_nothing_is_served_when_the_group_is_bad(self, project: Path) -> None:
        """The port must not be bound: a bound port is a pod that reports itself healthy."""
        with patch.object(entrypoint, "run_app") as run:
            entrypoint.main(environ={"BLUEPRINT_AGENTS": "not-in-this-image"})

        run.assert_not_called()

    def test_the_reason_reaches_stderr(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Printed as well as logged: logging is configured by AppBuilder, which has not run."""
        with patch.object(entrypoint, "run_app"):
            entrypoint.main(environ={"BLUEPRINT_AGENTS": "not-in-this-image"})

        assert "Cannot start:" in capsys.readouterr().err

    def test_the_message_names_what_was_wrong(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(entrypoint, "run_app"):
            entrypoint.main(environ={"BLUEPRINT_AGENTS": "not-in-this-image"})

        assert "not-in-this-image" in capsys.readouterr().err

    def test_a_critical_agent_that_cannot_be_loaded_exits_non_zero(self, project: Path) -> None:
        (project / "agents.toml").write_text('[agents.order]\nmodule = "no.such.module:registration"\n')

        with patch.object(entrypoint, "run_app") as run:
            status = entrypoint.main(environ={"BLUEPRINT_AGENTS": "order"})

        assert status == 1
        run.assert_not_called()

    def test_it_returns_a_status_rather_than_exiting(self, project: Path) -> None:
        """So a test asserts on the status; the __main__ guard is what turns it into an exit."""
        with patch.object(entrypoint, "run_app"):
            assert entrypoint.main(environ={"BLUEPRINT_AGENTS": "order"}) == 0


class TestItIsRunnableAsAModule:
    def test_the_module_has_a_main_guard(self) -> None:
        """`python -m blueprint.agents.entrypoint` is the container's command."""
        source = Path(entrypoint.__file__).read_text(encoding="utf-8")

        assert 'if __name__ == "__main__":' in source
        assert "sys.exit(main())" in source


class TestOneDeclarationServesBothDeploymentShapes:
    """The same module, run standalone and run as a group -- spec sec. 11's single ``main.py``.

    ``order_declaration`` above is the whole of what a project's ``main.py`` needs to contain:
    one unbuilt ``AppBuilder``, and no ``Config``, no ``run_app``, no ``if __name__``, no
    namespace and no group. These cases prove that one such module serves both shapes, so
    there is nothing to keep in sync between them.
    """

    def test_the_declaration_runs_standalone(self, project: Path) -> None:
        """What a migrated main.py does: build the declaration at the root and serve it.

        A builder separate from ``order_declaration`` only because a builder builds once and
        this file exercises both shapes; a real process runs one of them.
        """
        config = Config(settings_files=["settings.toml"])

        app = AppBuilder().with_service(OrderService).build(config)

        assert app is not None
        assert component_names() == ["order_service"]

    def test_the_same_declaration_runs_as_a_group_of_one(self, project: Path) -> None:
        """The entry point path: group size 1 is how an agent gets a process to itself."""
        app, _ = entrypoint.build_group_app(environ={"BLUEPRINT_AGENTS": "order"})

        assert app is not None
        assert component_names() == ["order_order_service"]

    def test_the_same_declaration_runs_beside_another_agent(self, project: Path) -> None:
        (project / "agents.toml").write_text(
            f'[agents.order]\nmodule = "{_THIS}:order_declaration"\n\n[agents.billing]\nmodule = "{_THIS}:order_declaration"\n'
        )

        entrypoint.build_group_app(environ={"BLUEPRINT_AGENTS": "order,billing"})

        assert component_names() == ["billing_order_service", "order_order_service"]

    def test_a_group_of_one_uses_the_agents_real_name(self, project: Path) -> None:
        """Deliberate, and the migration consequence to know about (spec sec. 11).

        Standalone runs at the root, so its component is ``order_service`` and its routes sit
        under ``/api``. A group of one runs under the agent's own name, so the component is
        ``order_order_service`` and the routes move to ``/api/order`` -- which is what makes
        local URLs and consumer identity match production instead of differing from it.
        """
        entrypoint.build_group_app(environ={"BLUEPRINT_AGENTS": "order"})

        assert component_names() == ["order_order_service"]
