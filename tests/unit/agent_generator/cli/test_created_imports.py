"""What ``asbs create`` adds to ``src/main.py`` is written the way that file already writes.

The generator emits relative imports throughout -- `from .handlers import OrderHandler` in
`main.py`, `from ..services import OrderService` in a component -- and `asbs create` used to
append absolute ones: `from src.handlers.order_placed_handler import OrderPlacedHandler`. Both
resolve, which is why nothing failed and why it survived; two styles in one file is how a later
move breaks exactly one of them.
"""

import json
from argparse import Namespace
from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.create import create_api, create_handler, create_service
from blueprint.agent_generator.cli.commands.setup import create_basic_config
from blueprint.agent_generator.generator.generator import AgentGenerator

PROJECT_NAME = "ImportDemo"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Path:
    """A scaffolded project, with the working directory inside it.

    The create commands read `Path.cwd()` for the project root and write their component file
    into `--output-dir`, so both have to be arranged for them.
    """
    config_file = tmp_path / "generator-config.json"
    config_file.write_text(json.dumps(create_basic_config(PROJECT_NAME)), encoding="utf-8")
    generator = AgentGenerator(str(config_file), str(tmp_path))
    generator.load_config()
    generator.generate()

    monkeypatch.chdir(tmp_path)
    capsys.readouterr()
    return tmp_path


def main_py(project: Path) -> str:
    return (project / "src" / "main.py").read_text(encoding="utf-8")


class TestEveryImportAddedIsRelative:
    """``from src.`` in a file whose own imports start with ``.`` is the mismatch under test."""

    def test_the_scaffolded_file_starts_out_relative(self, project: Path) -> None:
        """The premise: the style being matched is the generator's, not one invented here."""
        assert "from .handlers import" in main_py(project)
        assert "from src." not in main_py(project)

    def test_a_created_handler_is_imported_relatively(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        create_handler(Namespace(name="OrderPlaced", event_type="order.placed", output_dir=str(project / "src" / "handlers"), priority=10))
        capsys.readouterr()

        assert "from .handlers.order_placed_handler import OrderPlacedHandler" in main_py(project)
        assert "from src." not in main_py(project)

    def test_a_created_service_is_imported_relatively(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        create_service(Namespace(name="Pricing", output_dir=str(project / "src" / "services")))
        capsys.readouterr()

        assert "from .services.pricing_service import PricingService" in main_py(project)
        assert "from src." not in main_py(project)

    def test_a_created_api_imports_its_models_relatively_too(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Two files at once: the import added to `main.py`, and the one inside the API module
        the command writes -- which is a package deeper, so it needs `..` rather than `.`."""
        create_api(Namespace(name="Pricing", output_dir=str(project / "src" / "api")))
        capsys.readouterr()

        assert "from .api.pricing_api import PricingApi" in main_py(project)
        assert "from src." not in main_py(project)

        api_source = (project / "src" / "api" / "pricing_api.py").read_text(encoding="utf-8")
        assert "from ..models." in api_source
        assert "from src." not in api_source
