"""Pytest configuration for code review collaboration tests."""

import pytest
from pathlib import Path
from blueprint.agents.config import Config


@pytest.fixture
def test_config() -> Config:
    """Create a test configuration."""
    return Config(
        settings_files=["settings.toml"],
        root_path=Path(__file__).parent,
    )
