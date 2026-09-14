"""Every example under ``examples/`` is a project somebody can actually run.

These are repository-consistency checks, not integration tests: nothing here imports the
framework, starts a process or opens a socket. They lived under ``tests/integration/`` and were
therefore never run by CI, which is how they came to assert on four examples that had been deleted
and stayed red for a year (#80). They live here so that CI runs them.

**The list is derived from the directory, never hardcoded.** That is the whole lesson of #80: a
hardcoded list goes stale silently, and the failure surfaces years later as a wall of red about
projects nobody remembers. Derived, a reorganisation of ``examples/`` fails here, immediately, with
a message naming what moved.
"""

import tomllib
from pathlib import Path

import pytest

from blueprint.agents.clients.io.io_client_base import validate_subject_segment

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"

NOT_PROJECTS: dict[str, str] = {
    "shared_cache_demo": (
        "Standalone demo scripts (demo.py, demo_multiprocess.py, demo_redis.py, walkthrough.py) "
        "plus a README, illustrating the cache API. It has no declaration and no settings because "
        "it is not an application."
    ),
}
"""Directories under ``examples/`` that are not Blueprint projects, each with why.

Listed rather than silently skipped, and held to being genuinely not-a-project by
:func:`test_no_listed_directory_has_quietly_become_a_project` -- an allowlist that outlives its
entries is how a guard stops guarding.
"""


def _has_content(directory: Path) -> bool:
    """True if anything but compiled bytecode lives under ``directory``.

    A directory deleted from the repository leaves its ``__pycache__`` behind in a working copy
    -- git removes tracked files and nothing else -- and ``.pyc`` is gitignored, so the husk is
    invisible to ``git status`` and looks like a real example forever. That is not a hypothetical:
    ``customer_support_qa`` was deleted in ``ef6cd03`` and sat in ``NOT_PROJECTS`` describing a
    layout read off exactly such a husk, which passed locally and failed on CI's clean checkout.
    Deriving from files rather than from directories makes this test answer the same on both.
    """
    return any(path.is_file() and path.suffix != ".pyc" for path in directory.rglob("*"))


def example_directories() -> list[Path]:
    """Every directory under ``examples/`` that has content, derived rather than declared."""
    return sorted(path for path in EXAMPLES_DIR.iterdir() if path.is_dir() and not path.name.startswith((".", "__")) and _has_content(path))


def project_examples() -> list[Path]:
    """The example directories that are meant to be runnable projects."""
    return [path for path in example_directories() if path.name not in NOT_PROJECTS]


def example_id(path: Path) -> str:
    return path.name


class TestTheListIsDerived:
    """The check #80 asks for: a reorganisation of ``examples/`` fails here, not years later."""

    def test_there_are_examples_to_check(self) -> None:
        assert example_directories(), f"No example directories under {EXAMPLES_DIR}. Either examples/ moved, or this test did."

    def test_every_directory_is_a_project_or_is_listed(self) -> None:
        """A new directory is checked as a project unless somebody says why it is not."""
        assert [path.name for path in example_directories() if path.name in NOT_PROJECTS] == sorted(NOT_PROJECTS)

    @pytest.mark.parametrize("name", sorted(NOT_PROJECTS))
    def test_no_listed_directory_has_quietly_become_a_project(self, name: str) -> None:
        directory = EXAMPLES_DIR / name

        if not directory.is_dir():
            pytest.fail(f"examples/{name} no longer exists, so remove it from NOT_PROJECTS. It was listed because: {NOT_PROJECTS[name]}")

        assert not (directory / "settings.toml").is_file(), (
            f"examples/{name} now has a settings.toml, so it is a project and should be checked as one. "
            f"Remove it from NOT_PROJECTS. It was listed because: {NOT_PROJECTS[name]}"
        )


class TestEveryProjectIsRunnable:
    """What a reader needs to find in an example before they can run it."""

    @pytest.mark.parametrize("example", project_examples(), ids=example_id)
    def test_it_has_a_declaration(self, example: Path) -> None:
        """``main.py``, at the root or under ``src/`` -- both shapes are in use."""
        assert (example / "main.py").is_file() or (example / "src" / "main.py").is_file(), f"examples/{example.name} has no main.py"

    @pytest.mark.parametrize("example", project_examples(), ids=example_id)
    def test_it_has_settings(self, example: Path) -> None:
        assert (example / "settings.toml").is_file(), f"examples/{example.name} has no settings.toml"

    @pytest.mark.parametrize("example", project_examples(), ids=example_id)
    def test_its_settings_parse_and_name_the_application(self, example: Path) -> None:
        settings_file = example / "settings.toml"
        settings = tomllib.loads(settings_file.read_text(encoding="utf-8"))

        declared = "app_name" in settings or any(isinstance(value, dict) and "app_name" in value for value in settings.values())
        assert declared, (
            f"examples/{example.name} declares no app_name. It is the fallback identity for a root-namespace "
            "application -- the NATS queue group among other things -- so an example without one is not runnable."
        )

    @pytest.mark.parametrize("example", project_examples(), ids=example_id)
    def test_its_app_name_can_be_a_queue_group(self, example: Path) -> None:
        """Since P1, a root-namespace application's ``app_name`` *is* its NATS queue group, and
        the dead-letter subject is derived from it -- so a space in it is a subject the broker
        rejects, and the application raises at subscribe time.

        Every example carried one. Only ``webhook_relay`` was actually broken, because it is the
        only one on ``event_bus = "nats"``; the other four were an illegal value waiting for
        somebody to switch bus. An example that demonstrates a value the framework refuses is
        worse than no example, so this holds all five to what the client will accept.
        """
        settings = tomllib.loads((example / "settings.toml").read_text(encoding="utf-8"))
        names = [settings["app_name"]] if "app_name" in settings else []
        names += [value["app_name"] for value in settings.values() if isinstance(value, dict) and "app_name" in value]

        for name in names:
            validate_subject_segment(name, source=f"examples/{example.name} app_name", subject=f"{name}.dead-letter")

    @pytest.mark.parametrize("example", project_examples(), ids=example_id)
    def test_it_has_a_readme(self, example: Path) -> None:
        assert (example / "README.md").is_file(), f"examples/{example.name} has no README.md"
