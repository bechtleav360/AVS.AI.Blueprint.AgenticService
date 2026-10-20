"""What ``asbs create handler``, ``asbs create service`` and ``asbs setup`` write and print.

``create handler --event-type X`` took X for a docstring only, while the generated handler reads
``<handler>.input_event_type`` from the settings at startup -- a key nothing wrote. It is written
now, the way ``create agent`` writes its runtime's block, and read back here through the
validator's view of the settings, which layers them as the process does.
"""

import sys
from argparse import Namespace
from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands import setup
from blueprint.agent_generator.cli.commands.create import create_handler, create_service
from blueprint.agent_generator.cli.commands.validate import ProcessSettings


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "settings.toml").write_text('[default]\napp_name = "the-project"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _handler(event_type: str = "order.placed") -> Namespace:
    return Namespace(name="OrderPlaced", event_type=event_type, priority=10, output_dir="src/handlers")


class TestCreateHandler:
    def test_the_event_type_is_written_where_the_handler_reads_it(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        create_handler(_handler())
        capsys.readouterr()

        source = (project / "src" / "handlers" / "order_placed_handler.py").read_text(encoding="utf-8")
        assert 'self.config.get("order_placed_handler"' in source, "the generated handler reads this section"
        view = ProcessSettings.load(project, "production").root_view()
        assert view.get("order_placed_handler.input_event_type") == "order.placed"

    def test_an_existing_section_is_left_alone(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        settings = project / "settings.toml"
        settings.write_text('[default]\napp_name = "p"\n\n[default.order_placed_handler]\ninput_event_type = "mine"\n', encoding="utf-8")

        create_handler(_handler())
        capsys.readouterr()

        assert settings.read_text(encoding="utf-8").count("[default.order_placed_handler]") == 1
        assert ProcessSettings.load(project).root_view().get("order_placed_handler.input_event_type") == "mine"


class TestCreateService:
    def test_the_docstring_names_the_service_not_a_placeholder(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        create_service(Namespace(name="Invoice", output_dir="src/services"))
        capsys.readouterr()

        source = next((project / "src" / "services").glob("*.py")).read_text(encoding="utf-8")
        assert "cli_generated" not in source


class TestSetupPrintsWhatItWrites:
    def test_every_file_written_at_the_top_is_in_the_printed_tree(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        setup.run(Namespace(project_name="Demo", output_dir=str(tmp_path), overwrite=False, verbose=False, group=False))
        out = capsys.readouterr().out
        tree = out.split("Project structure:")[1].split("Next steps:")[0]

        written = sorted(path.name for path in tmp_path.iterdir() if path.name != "__pycache__")
        missing = [name for name in written if f" {name}" not in tree and f" {name}/" not in tree]
        assert not missing, f"setup wrote {missing} and its tree does not show them"


@pytest.mark.skipif(sys.platform == "emscripten", reason="needs a subprocess")
def test_the_generated_declaration_test_passes_after_the_app_was_built(tmp_path: Path) -> None:
    """Guide item: building the app in the same pytest session used to fail test_declaration."""
    import subprocess

    setup.run(Namespace(project_name="Demo", output_dir=str(tmp_path), overwrite=False, verbose=False, group=False))
    (tmp_path / "tests" / "test_0_builds_first.py").write_text(
        "from src.main import create_app\n\n\ndef test_build() -> None:\n    create_app()\n", encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_0_builds_first.py", "tests/test_declaration.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]


@pytest.mark.skipif(sys.platform == "emscripten", reason="needs a subprocess")
def test_a_fresh_project_starts_the_way_its_container_does(tmp_path: Path) -> None:
    """``asbs setup`` must produce a project that starts as generated.

    Its handler reads ``input_event_type``, which ``setup`` does not write, so a stricter startup
    check there stops every new project (N18). Started in production, as both Dockerfiles do,
    through ``create_app()`` and the lifespan; a subprocess keeps its configuration out of this one.
    """
    import os
    import subprocess

    setup.run(Namespace(project_name="Demo", output_dir=str(tmp_path), overwrite=False, verbose=False, group=False))
    script = "from fastapi.testclient import TestClient\nfrom src.main import create_app\n\nwith TestClient(create_app()):\n    pass\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "DYNACONF_APP_ENVIRONMENT": "production"},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
