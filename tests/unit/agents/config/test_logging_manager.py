"""Unit tests for LoggingManager.

These tests are explicitly excluded from the mock_logging_configure autouse
fixture in conftest.py so that real logging behaviour can be exercised.
"""

import logging
from unittest.mock import patch

import pytest

from blueprint.agents.config.custom_logging import CorrelationContext, LoggingManager


class TestLoggingManager:
    """Tests for LoggingManager configuration and helpers."""

    @pytest.fixture(autouse=True)
    def restore_loggers(self):
        """Snapshot global logging state and restore it after every test."""
        root = logging.getLogger()
        uvicorn_access = logging.getLogger("uvicorn.access")
        noisy = ["httpx", "httpcore", "uvicorn", "opentelemetry", "openai", "apscheduler"]

        snapshots = {name: (logging.getLogger(name).level, logging.getLogger(name).filters[:]) for name in noisy}
        orig_root_level = root.level
        orig_root_handlers = root.handlers[:]
        orig_root_filters = root.filters[:]
        orig_uvicorn_filters = uvicorn_access.filters[:]
        orig_uvicorn_level = uvicorn_access.level

        yield

        root.handlers = orig_root_handlers
        root.filters = orig_root_filters
        root.setLevel(orig_root_level)
        uvicorn_access.filters = orig_uvicorn_filters
        uvicorn_access.setLevel(orig_uvicorn_level)
        for name, (level, filters) in snapshots.items():
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.filters = filters

    @pytest.fixture
    def manager(self) -> LoggingManager:
        return LoggingManager()

    # ------------------------------------------------------------------
    # configure() behaviour
    # ------------------------------------------------------------------

    def test_configure_sets_configured_flag(self, manager: LoggingManager) -> None:
        with (
            patch.object(manager, "_setup_basic_config"),
            patch.object(manager, "_attach_correlation_filter"),
            patch.object(manager, "_attach_health_check_filter"),
            patch.object(manager, "_suppress_noisy_loggers"),
        ):
            manager.configure()
        assert manager._configured is True

    def test_configure_is_idempotent(self, manager: LoggingManager) -> None:
        """A second configure() call is silently ignored."""
        manager._configured = True
        with patch.object(manager, "_setup_basic_config") as mock_setup:
            manager.configure()
        mock_setup.assert_not_called()

    def test_configure_attaches_correlation_filter_to_root(self, manager: LoggingManager) -> None:
        with (
            patch.object(manager, "_setup_basic_config"),
            patch.object(manager, "_attach_health_check_filter"),
            patch.object(manager, "_suppress_noisy_loggers"),
        ):
            manager.configure()
        assert manager._correlation_filter in logging.getLogger().filters

    def test_configure_attaches_health_check_filter_to_uvicorn_access(self, manager: LoggingManager) -> None:
        with (
            patch.object(manager, "_setup_basic_config"),
            patch.object(manager, "_attach_correlation_filter"),
            patch.object(manager, "_suppress_noisy_loggers"),
        ):
            manager.configure()
        assert manager._health_check_filter in logging.getLogger("uvicorn.access").filters

    # ------------------------------------------------------------------
    # Format strings
    # ------------------------------------------------------------------

    def test_text_format_contains_correlation_id(self, manager: LoggingManager) -> None:
        fmt = manager._get_format_string("text")
        assert "%(correlation_id)s" in fmt

    def test_text_format_contains_level_and_name(self, manager: LoggingManager) -> None:
        fmt = manager._get_format_string("text")
        assert "%(levelname)s" in fmt
        assert "%(name)s" in fmt

    def test_json_format_contains_correlation_id_key(self, manager: LoggingManager) -> None:
        fmt = manager._get_format_string("json")
        assert "correlation_id" in fmt

    def test_json_format_contains_level_key(self, manager: LoggingManager) -> None:
        fmt = manager._get_format_string("json")
        assert "level" in fmt

    def test_unknown_format_falls_back_to_text(self, manager: LoggingManager) -> None:
        assert manager._get_format_string("xml") == manager._get_format_string("text")

    # ------------------------------------------------------------------
    # Noisy logger suppression
    # ------------------------------------------------------------------

    def test_suppress_noisy_loggers_sets_httpx_to_warning(self, manager: LoggingManager) -> None:
        manager._suppress_noisy_loggers()
        assert logging.getLogger("httpx").level == logging.WARNING

    def test_suppress_noisy_loggers_sets_httpcore_to_warning(self, manager: LoggingManager) -> None:
        manager._suppress_noisy_loggers()
        assert logging.getLogger("httpcore").level == logging.WARNING

    def test_suppress_noisy_loggers_sets_openai_to_info(self, manager: LoggingManager) -> None:
        manager._suppress_noisy_loggers()
        assert logging.getLogger("openai").level == logging.INFO

    # ------------------------------------------------------------------
    # set_level / get_logger helpers
    # ------------------------------------------------------------------

    def test_set_level_debug_changes_root_logger(self, manager: LoggingManager) -> None:
        manager.set_level("DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_set_level_warning_changes_root_logger(self, manager: LoggingManager) -> None:
        manager.set_level("WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_get_logger_returns_named_logger(self, manager: LoggingManager) -> None:
        logger = manager.get_logger("my.component")
        assert logger.name == "my.component"
        assert isinstance(logger, logging.Logger)

    # ------------------------------------------------------------------
    # Custom CorrelationContext injection
    # ------------------------------------------------------------------

    def test_custom_correlation_context_used_in_filter(self) -> None:
        custom_ctx = CorrelationContext()
        custom_ctx.set("custom-id")
        manager = LoggingManager(correlation=custom_ctx)
        record = logging.LogRecord(name="t", level=logging.INFO, pathname="", lineno=0, msg="", args=(), exc_info=None)
        manager._correlation_filter.filter(record)
        assert record.correlation_id == "custom-id"
