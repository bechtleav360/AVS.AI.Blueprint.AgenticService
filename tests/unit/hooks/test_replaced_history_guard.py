"""Regression tests for the Claude Code push guard `.claude/hooks/replaced-history-guard.sh`.

The hook reads the proposed Bash call as JSON and refuses (exit 2) a `git push` of a branch that
descends from the replaced root commit. Each test builds a throwaway repository with a root of its
own and runs a copy of the hook whose REPLACED_ROOT names that commit; nothing is pushed anywhere.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[3] / ".claude" / "hooks" / "replaced-history-guard.sh"
SH = shutil.which("sh") or "sh"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None or shutil.which("git") is None, reason="needs sh and git on PATH")

REFUSED = 2
LET_THROUGH = 0

# No environment is passed explicitly: a failing call's arguments end up in the traceback.
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def _git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` and return its stdout."""
    return subprocess.run([*GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class Project:
    """A repository whose `main` is clean and whose `old` descends from the replaced root."""

    def __init__(self, path: Path, hook: Path) -> None:
        self.path = path
        self.hook = hook

    def run(self, command: str, spaced: bool = False) -> subprocess.CompletedProcess[str]:
        """Feed the hook the PreToolUse input for a Bash call of ``command``."""
        payload = {
            "session_id": "test",
            "cwd": str(self.path),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command, "description": "test"},
        }
        text = json.dumps(payload) if spaced else json.dumps(payload, separators=(",", ":"))
        return subprocess.run([SH, self.hook.as_posix()], input=text, capture_output=True, text=True, cwd=self.path)


@pytest.fixture
def scratch(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A directory with default permissions, which git (and the hook's git) accepts as safe.

    pytest's ``tmp_path`` is owner-only (mode 0o700), and Git for Windows cannot enter such a
    directory ("cannot change to ...: Permission denied"). Where the temporary directory belongs to
    another owner than the user (e.g. the Administrators group), git refuses it as of dubious
    ownership; ``safe.directory`` is only read from command-line scope or above, hence the variables.
    """
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.directory")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "*")
    path = Path(tempfile.gettempdir()) / f"guard-test-{uuid.uuid4().hex}"
    path.mkdir()
    yield path

    def make_writable_and_retry(function: Callable[[str], object], name: str, _: BaseException) -> None:
        os.chmod(name, stat.S_IWRITE)  # git's object files are read-only
        function(name)

    shutil.rmtree(path, onexc=make_writable_and_retry)


@pytest.fixture
def make_project(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Project]:
    def make(name: str) -> Project:
        path = scratch / name
        path.mkdir()
        _git(path, "init", "-q", "-b", "main")
        _git(path, "commit", "-q", "--allow-empty", "-m", "clean")
        _git(path, "checkout", "-q", "-b", "old")
        _git(path, "commit", "-q", "--allow-empty", "-m", "replaced root")
        root = _git(path, "rev-parse", "HEAD")
        _git(path, "commit", "-q", "--allow-empty", "-m", "replaced child")
        _git(path, "checkout", "-q", "main")

        hook = scratch / "guard.sh"
        script = HOOK.read_text(encoding="utf-8")
        original = next(line for line in script.splitlines() if line.startswith("REPLACED_ROOT="))
        hook.write_text(script.replace(original, f"REPLACED_ROOT={root}"), encoding="utf-8", newline="\n")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(path))
        return Project(path, hook)

    return make


@pytest.fixture
def project(make_project: Callable[[str], Project]) -> Project:
    return make_project("project")


def _path_forms(path: Path, bare: bool = True) -> list[str]:
    """The ways a command can name ``path``: bare, single- and double-quoted, native separators."""
    forms = [f'"{path.as_posix()}"', f"'{path.as_posix()}'", f'"{path}"']
    if bare:
        forms.insert(0, path.as_posix())
    return list(dict.fromkeys(forms))


REFUSED_COMMANDS = [
    "git push origin old",
    "git push --dry-run origin old",
    "git push origin +old:other",
    "git push origin main old",
    "git push --all origin",
    "git push --mirror origin",
    "git -c push.default=current push origin old",
    "git status && git push origin old",
    "git status; git push origin old",
]

LET_THROUGH_COMMANDS = [
    "git push origin main",
    "git push origin",
    "git push origin --delete old",
    "git push --tags origin",
    "git log --oneline -1",
    "git push origin main && git log old",
]


@pytest.mark.parametrize("spaced", [False, True], ids=["compact", "spaced"])
@pytest.mark.parametrize("command", REFUSED_COMMANDS)
def test_a_push_of_the_replaced_history_is_refused(project: Project, command: str, spaced: bool) -> None:
    result = project.run(command, spaced)
    assert result.returncode == REFUSED, result.stderr
    assert "old" in result.stderr


@pytest.mark.parametrize("spaced", [False, True], ids=["compact", "spaced"])
@pytest.mark.parametrize("command", LET_THROUGH_COMMANDS)
def test_other_commands_are_let_through(project: Project, command: str, spaced: bool) -> None:
    assert project.run(command, spaced).returncode == LET_THROUGH


def test_a_push_of_the_current_branch_is_refused_when_it_carries_the_replaced_history(project: Project) -> None:
    _git(project.path, "checkout", "-q", "old")
    assert project.run("git push origin").returncode == REFUSED
    assert project.run("git push").returncode == REFUSED


@pytest.mark.parametrize("spaced", [False, True], ids=["compact", "spaced"])
def test_the_repository_is_found_however_the_command_names_it(project: Project, spaced: bool) -> None:
    for form in _path_forms(project.path):
        for command in (
            f"cd {form} && git push origin old",
            f"git -C {form} push origin old",
            f"cd {form}\ngit push origin old",
        ):
            assert project.run(command, spaced).returncode == REFUSED, command
        for command in (f"cd {form} && git push origin main", f"git -C {form} push origin --delete old"):
            assert project.run(command, spaced).returncode == LET_THROUGH, command


def test_a_quoted_path_may_contain_spaces(make_project: Callable[[str], Project]) -> None:
    project = make_project("my project")
    for form in _path_forms(project.path, bare=False):
        assert project.run(f"cd {form} && git push origin old").returncode == REFUSED, form
        assert project.run(f"git -C {form} push origin old").returncode == REFUSED, form


def test_a_repository_outside_the_project_is_not_inspected(project: Project, scratch: Path) -> None:
    # The hook runs before the user approves the command, so it never runs git where the command
    # merely points; CI ("No replaced history") refuses such a branch instead.
    outside = scratch / "outside"
    _git(scratch, "clone", "-q", str(project.path), str(outside))
    _git(outside, "branch", "old", "origin/old")
    for form in _path_forms(outside):
        assert project.run(f"git -C {form} push origin old").returncode == LET_THROUGH, form
