"""A process in development mode says so, once, at startup (M1).

``app_environment`` defaults to ``"development"``, and development is where fallbacks such as a
localhost broker apply. A deployment that forgot to leave it therefore runs on those fallbacks,
and this WARNING is what makes that visible in its own log.
"""

import logging
from unittest.mock import MagicMock

import pytest

from blueprint.agents.app_builder import AppBuilder

LOGGER = "blueprint.agents.app_builder"


def _config(**values: object) -> MagicMock:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: values.get(key, default)
    return config


@pytest.mark.parametrize("environment", [None, "development", "Development"])
def test_development_is_announced(environment: str | None, caplog: pytest.LogCaptureFixture) -> None:
    values = {} if environment is None else {"app_environment": environment}
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        AppBuilder._warn_if_development(_config(**values))
    assert "running in development mode" in caplog.text
    assert "not suitable for production" in caplog.text


def test_another_environment_is_not(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        AppBuilder._warn_if_development(_config(app_environment="production"))
    assert caplog.records == []
