"""Unit tests for ``run_app`` and the uvicorn log-level translation."""

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.config import Config
from blueprint.agents.utils import run_app, uvicorn_log_level

Settings = dict[str, Any]


def make_config(**settings: Any) -> MagicMock:
    """Return a Config stand-in answering ``get`` from ``settings``, defaults otherwise."""
    config = MagicMock(spec=Config)
    config.get.side_effect = lambda key, default=None: settings.get(key, default)
    return config


def serve(**settings: Any) -> dict[str, Any]:
    """Run ``run_app`` against a mocked uvicorn and return the keyword arguments it received."""
    app = MagicMock()
    with patch("uvicorn.run") as run:
        run_app(app, make_config(**settings))
    assert run.call_args.args == (app,)
    return dict(run.call_args.kwargs)


class TestServerArguments:
    def test_host_and_port_come_from_config(self) -> None:
        kwargs = serve(app_host="127.0.0.1", app_port=9001)
        assert (kwargs["host"], kwargs["port"]) == ("127.0.0.1", 9001)

    def test_the_defaults_bind_all_interfaces_on_8000(self) -> None:
        """A container cannot know which interface its traffic arrives on."""
        kwargs = serve()
        assert (kwargs["host"], kwargs["port"]) == ("0.0.0.0", 8000)

    def test_a_string_port_is_coerced(self) -> None:
        """An environment override arrives as text, and uvicorn wants an int."""
        assert serve(app_port="9002")["port"] == 9002

    def test_reload_is_never_enabled(self) -> None:
        """Auto-reload needs an import string; uvicorn cannot restart an object already built."""
        assert serve(app_environment="development")["reload"] is False


class TestDevelopment:
    def test_development_logs_at_debug(self) -> None:
        assert serve(app_environment="development", log_level="WARNING")["log_level"] == "debug"

    def test_development_ignores_configured_workers(self) -> None:
        """The refusal below is a production concern; in development it is simply one worker."""
        assert serve(app_environment="development", app_workers=4)["workers"] == 1

    def test_the_default_environment_is_development(self) -> None:
        assert serve()["log_level"] == "debug"


class TestProduction:
    def test_the_configured_level_is_translated(self) -> None:
        assert serve(app_environment="production", log_level="WARNING")["log_level"] == "warning"

    def test_the_level_defaults_to_info(self) -> None:
        assert serve(app_environment="production")["log_level"] == "info"

    def test_one_worker_is_allowed(self) -> None:
        assert serve(app_environment="production", app_workers=1)["workers"] == 1

    @pytest.mark.parametrize("workers", [2, "4"])
    def test_more_than_one_worker_is_refused(self, workers: object) -> None:
        """uvicorn would sys.exit here, naming 'reload' -- and N workers means N transports."""
        with pytest.raises(ValueError, match="one application per process"):
            serve(app_environment="production", app_workers=workers)

    def test_the_refusal_happens_before_the_server_starts(self) -> None:
        with patch("uvicorn.run") as run:
            with pytest.raises(ValueError):
                run_app(MagicMock(), make_config(app_environment="production", app_workers=8))
        run.assert_not_called()


class TestUvicornLogLevel:
    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            ("INFO", "info"),
            ("debug", "debug"),
            (" WARNING ", "warning"),
            ("critical", "critical"),
            ("trace", "trace"),
        ],
    )
    def test_a_known_level_is_lower_cased(self, configured: str, expected: str) -> None:
        assert uvicorn_log_level(configured) == expected

    def test_an_unknown_level_falls_back_to_info_and_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        """Nothing outside the process depends on this level, so it warns rather than raising."""
        with caplog.at_level(logging.WARNING):
            assert uvicorn_log_level("WARN") == "info"
        assert "uvicorn understands" in caplog.text
