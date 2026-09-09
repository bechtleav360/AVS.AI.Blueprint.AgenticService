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
from blueprint.agents.app_builder import AgentRegistration
from blueprint.agents.component.component import Component
from blueprint.agents.services.service_base import ServiceBase

_THIS = "tests.unit.agents.test_entrypoint"


class OrderService(ServiceBase):
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


order_registration = AgentRegistration().with_service(OrderService)


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
    (tmp_path / "agents.toml").write_text(f'[agents.order]\nmodule = "{_THIS}:order_registration"\n')
    (tmp_path / "settings.toml").write_text('[development]\napp_environment = "development"\napp_name = "the-process"\napp_port = 8000\n')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def component_names() -> list[str]:
    registry = Component.shared_registry
    assert registry is not None
    return sorted(registry.get_component_names_by_type(Component))


class TestBuild:
    def test_it_builds_the_group_the_environment_names(self, project: Path) -> None:
        app, config = entrypoint.build(environ={"BLUEPRINT_AGENTS": "order", "BLUEPRINT_GROUP": "finance"})

        assert app is not None
        assert config.get("app_name") == "the-process"
        assert "order_order_service" in component_names()

    def test_it_reads_the_group_file_when_there_is_one(self, project: Path) -> None:
        (project / "deployment-groups.yaml").write_text("groups:\n  - name: finance\n    agents: [order]\n")

        entrypoint.build(environ={})

        assert "order_order_service" in component_names()

    def test_a_resolution_failure_propagates(self, project: Path) -> None:
        """build() raises; deciding what to do about it is main()'s job."""
        from blueprint.agents.group_config import GroupConfigError

        with pytest.raises(GroupConfigError):
            entrypoint.build(environ={"BLUEPRINT_AGENTS": "not-in-this-image"})


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
