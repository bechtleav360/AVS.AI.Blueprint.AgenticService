"""Unit tests for the scheduler scaffold emitted by ``asbs create scheduler``."""

import ast
from argparse import Namespace
from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.create import create_scheduler


@pytest.fixture
def scaffold(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> str:
    """Generate a scheduler into a temporary directory and return its source."""
    create_scheduler(Namespace(name="cleanup", output_dir=str(tmp_path), cron="0 * * * *"))
    capsys.readouterr()
    return (tmp_path / "cleanup_scheduler.py").read_text(encoding="utf-8")


def _method(source: str, name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"the scaffold has no '{name}' method")


def _calls_super(method: ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(method):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method.name
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        ):
            return True
    return False


class TestSchedulerScaffold:
    def test_scaffold_is_valid_python(self, scaffold: str) -> None:
        """The previous template left an empty ``try:`` block, so it did not even parse."""
        ast.parse(scaffold)

    def test_declared_crontab_is_carried_through(self, scaffold: str) -> None:
        assert 'crontab="0 * * * *"' in scaffold

    def test_on_startup_calls_super(self, scaffold: str) -> None:
        """Without it the base class never starts the timer or wires the tick handler."""
        assert _calls_super(_method(scaffold, "on_startup"))

    def test_on_shutdown_calls_super(self, scaffold: str) -> None:
        assert _calls_super(_method(scaffold, "on_shutdown"))

    def test_tick_does_not_swallow_its_own_failure(self, scaffold: str) -> None:
        """A caught tick failure acknowledges the delivery as successful work."""
        assert not [node for node in ast.walk(_method(scaffold, "tick")) if isinstance(node, ast.Try)]

    def test_scheduler_mode_is_explained(self, scaffold: str) -> None:
        assert "scheduler_mode" in scaffold
