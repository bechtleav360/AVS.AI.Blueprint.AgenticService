"""Unit tests for the `asbs dev` command (issue #15, and phase 10's group-of-one dev server)."""

import os
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from blueprint.agent_generator.cli.commands import dev

AGENT_MAP = '[agents.orders]\nmodule = "src.main:agent"\n\n[agents.billing]\nmodule = "src.main:agent"\n'


@pytest.fixture(autouse=True)
def _no_inherited_group(monkeypatch: pytest.MonkeyPatch):
    """Isolate the group variables in both directions.

    The command reads the environment before it defaults, so a developer's own must not leak
    in; and it *sets* BLUEPRINT_AGENTS in this process so the server it spawns inherits it, so
    what it sets must not leak out into the rest of the suite.
    """
    monkeypatch.delenv(dev.AGENTS_ENV, raising=False)
    monkeypatch.delenv(dev.GROUP_ENV, raising=False)
    yield
    os.environ.pop(dev.AGENTS_ENV, None)


def _run(tmp_path: Path, **overrides: object) -> list[str]:
    """Run the command in ``tmp_path`` with the server mocked, and return the command it spawned."""
    args = Namespace(host="127.0.0.1", port=8000, agents=None)
    for key, value in overrides.items():
        setattr(args, key, value)

    with patch("blueprint.agent_generator.cli.commands.dev.subprocess.run") as mock_run:
        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            dev.run(args)
        finally:
            os.chdir(cwd)

    return list(mock_run.call_args.args[0])


class TestRunInterpreter:
    def test_spawns_uvicorn_with_sys_executable_not_literal_python(self, tmp_path: Path) -> None:
        """The subprocess must use the launching interpreter (venv-correct on Windows),
        not the literal "python" which can resolve to uv's base interpreter."""
        (tmp_path / "agents.toml").write_text(AGENT_MAP, encoding="utf-8")

        cmd = _run(tmp_path)

        assert cmd[0] == sys.executable
        assert cmd[0] != "python"


class TestAProjectWithAnAgentMap:
    """It is served as a group, under the agents' real namespaces."""

    def test_it_serves_the_frameworks_group_factory(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(AGENT_MAP, encoding="utf-8")

        cmd = _run(tmp_path)

        assert cmd[1:5] == ["-m", "uvicorn", "blueprint.agents.entrypoint:create_group_app", "--factory"]
        assert cmd[-5:] == ["--reload", "--host", "127.0.0.1", "--port", "8000"]

    def test_every_agent_in_the_map_is_hosted_by_default(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(AGENT_MAP, encoding="utf-8")

        _run(tmp_path)

        assert os.environ[dev.AGENTS_ENV] == "orders,billing"

    def test_a_subset_can_be_named(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(AGENT_MAP, encoding="utf-8")

        _run(tmp_path, agents="billing")

        assert os.environ[dev.AGENTS_ENV] == "billing"

    def test_an_environment_that_already_names_a_group_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A developer reproducing a deployment must not have it overwritten from the agent map."""
        (tmp_path / "agents.toml").write_text(AGENT_MAP, encoding="utf-8")
        monkeypatch.setenv(dev.GROUP_ENV, "checkout")

        _run(tmp_path)

        assert dev.AGENTS_ENV not in os.environ

    def test_an_empty_map_stops_rather_than_serving_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text("# nothing here\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exit_info:
            _run(tmp_path)

        assert exit_info.value.code == 1


class TestAProjectWithoutAnAgentMap:
    """A project written before the agent map still builds its own application."""

    def test_it_is_served_as_it_always_was(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("app = None\n", encoding="utf-8")

        cmd = _run(tmp_path)

        assert cmd[1:4] == ["-m", "uvicorn", "src.main:app"]
        assert "--factory" not in cmd

    def test_neither_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exit_info:
            _run(tmp_path)

        assert exit_info.value.code == 1
