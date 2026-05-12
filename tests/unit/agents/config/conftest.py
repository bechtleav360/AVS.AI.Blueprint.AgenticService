"""Shared fixtures for config unit tests."""

import textwrap
import pytest

from collections.abc import Callable, Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

from blueprint.agents.config import Config

WriteSettings = Callable[..., Path]


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def base_settings_file() -> Path:
    """Return path to the minimal valid base settings file."""
    return FIXTURES_DIR / "settings_base.toml"


@pytest.fixture
def api_key_settings_file() -> Path:
    """Return path to the multi-runtime API key settings file."""
    return FIXTURES_DIR / "settings_api_key_test.toml"


@pytest.fixture
def write_settings(tmp_path: Path) -> WriteSettings:
    """Write TOML content to a temporary file and return its Path.

    Usage::

        def test_something(write_settings):
            f = write_settings('''
                [development]
                app_port = 8000
                ...
            ''')
            config = Config(settings_files=[str(f)], root_path=str(f.parent))
    """

    def _write(content: str, filename: str = "settings.toml") -> Path:
        path = tmp_path / filename
        path.write_text(textwrap.dedent(content))
        return path

    return _write


@pytest.fixture
def base_config(base_settings_file: Path) -> Config:
    """Return a Config loaded from the minimal base settings file."""
    return Config(
        settings_files=[str(base_settings_file)],
        root_path=str(base_settings_file.parent),
    )


@pytest.fixture(autouse=True)
def mock_logging_configure(request: pytest.FixtureRequest) -> Generator[MagicMock | None]:
    """Prevent Config.__init__ from mutating global logging state during config tests.

    Skipped automatically for test_logging_manager tests that exercise
    LoggingManager directly and need real logging behaviour.
    """
    if "test_logging_manager" in request.node.nodeid:
        yield
        return

    with patch("blueprint.agents.config.config.LoggingManager") as mock_mgr:
        mock_mgr.return_value.configure.return_value = None
        yield mock_mgr
