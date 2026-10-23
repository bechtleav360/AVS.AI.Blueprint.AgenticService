"""What the generator writes and prints must not contradict the runtime.

Each of these held a sentence the runtime disproved: a disk cache "so one replica runs it" (its
claim holds within one process), dedup that needed only two keys (it needs ``.with_cache()`` too),
a ``debug`` key nothing reads, and a group Dockerfile calling a standalone agent "a group of one".
"""

import sys
from pathlib import Path

import pytest

from blueprint.agent_generator.cli import main as cli_main
from blueprint.agent_generator.cli.commands import group_setup

BASE_FILES = Path(cli_main.__file__).resolve().parent.parent / "base_files"


def _text(relative: str) -> str:
    return (BASE_FILES / relative).read_text(encoding="utf-8")


class TestSettingsTemplate:
    def test_the_dedup_comment_names_the_cache(self) -> None:
        assert ".with_cache()" in _text("settings.txt").split("# idempotency_enabled")[0]

    def test_it_writes_no_key_nothing_reads(self) -> None:
        assert "debug = true" not in _text("settings.txt")

    def test_a_disk_cache_is_not_said_to_coordinate_replicas(self) -> None:
        text = " ".join(_text("settings.txt").split())
        assert "within one process" in text
        assert "Redis" in text


class TestHandlerTemplate:
    def test_the_dedup_comment_names_the_cache(self) -> None:
        assert ".with_cache()" in _text("src/handlers/handler.txt")


class TestGroupFiles:
    def test_the_group_dockerfile_does_not_call_a_standalone_agent_a_group(self) -> None:
        assert "a standalone agent is a group of one" not in _text("group_Dockerfile")

    def test_the_group_dockerfile_says_where_an_agents_secrets_are_mounted(self) -> None:
        assert "/app/<root>/.secrets.toml" in _text("group_Dockerfile")

    def test_the_group_settings_do_not_promise_one_replica_on_disk(self) -> None:
        text = " ".join(group_setup.GROUP_SETTINGS.split())
        assert "within one process" in text


class TestDevHelp:
    def test_the_description_says_an_agent_directory_is_served_alone(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["asbs", "dev", "--help"])
        with pytest.raises(SystemExit):
            cli_main.main()
        out = " ".join(capsys.readouterr().out.split())
        assert "alone" in out and "root namespace" in out
