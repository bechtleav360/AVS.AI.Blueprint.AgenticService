"""What ``asbs create agent`` writes into ``settings.toml``, read back by the framework.

The command's whole output is a pair of prompt files, a block of configuration and a
registration in ``main.py``. The configuration block is the half nothing would report if it were
wrong: a table whose name the framework does not look up is not an error, it is simply never
read, and the project runs with the defaults while the file says otherwise. So the assertion
here is not that the text was written -- it is that ``Config`` hands the written values back.
"""

from argparse import Namespace
from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.create import create_agent
from blueprint.agents.config import Config

AGENT = "pricing"
RUNTIME = "pricing_agent"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Path:
    """Run ``asbs create agent pricing`` in an otherwise empty project and return its root.

    ``create_agent`` reads the working directory rather than an output path, so the directory is
    what has to be moved into.
    """
    (tmp_path / "settings.toml").write_text(
        '[default]\napp_name = "the-project"\napp_environment = "development"\n'
        'model_provider = "openai"\nmodel_api_key = "not-a-real-key"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    create_agent(Namespace(name=AGENT))
    capsys.readouterr()
    return tmp_path


def load(project: Path) -> Config:
    return Config(settings_files=["settings.toml"], root_path=str(project))


class TestTheRuntimeItConfigures:
    def test_the_model_is_the_one_written(self, project: Path) -> None:
        ai_config = load(project).get_ai_config(RUNTIME)

        assert ai_config.provider == "openai"
        assert ai_config.model_name == "gpt-5-mini"

    def test_the_model_settings_reach_the_provider_client(self, project: Path) -> None:
        """Written as ``[.models]`` these were read by nothing: ``get_ai_config`` looks up
        ``runtimes.<name>.model_settings``, and hands exactly that to the client."""
        assert load(project).get_ai_config(RUNTIME).model_settings == {
            "openai_reasoning_effort": "low",
            "openai_reasoning_summary": "detailed",
        }

    def test_no_table_is_written_that_nothing_reads(self, project: Path) -> None:
        assert ".models]" not in (project / "settings.toml").read_text(encoding="utf-8")


class TestWhenThereIsNoMainPyToRegisterIn:
    """The fallback path has to survive being taken."""

    def test_it_prints_the_registration_to_add_by_hand(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The runtime name was derived inside the try block that needs ``src/main.py``, so the
        instructions printed when that file is missing raised ``UnboundLocalError`` instead --
        after the prompts and the settings block had already been written."""
        monkeypatch.chdir(tmp_path)

        create_agent(Namespace(name=AGENT))

        printed = capsys.readouterr().out
        assert f'.with_agent({RUNTIME}, name="{RUNTIME}")' in printed
        assert f'AgentBuilder(runtime_name="{RUNTIME}")' in printed
