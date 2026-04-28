"""Unit tests for HealthCheckFilter."""

import logging

import pytest

from blueprint.agents.config.custom_logging import HealthCheckFilter


def _make_record(name: str, message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )


class TestHealthCheckFilter:
    @pytest.fixture
    def health_filter(self) -> HealthCheckFilter:
        return HealthCheckFilter()

    def test_filters_live_200(self, health_filter: HealthCheckFilter) -> None:
        record = _make_record("uvicorn.access", "GET /health/live HTTP/1.1 200 0")
        assert health_filter.filter(record) is False

    def test_filters_ready_200(self, health_filter: HealthCheckFilter) -> None:
        record = _make_record("uvicorn.access", "GET /health/ready HTTP/1.1 200 0")
        assert health_filter.filter(record) is False

    def test_filters_ready_204(self, health_filter: HealthCheckFilter) -> None:
        record = _make_record("uvicorn.access", "GET /health/ready HTTP/1.1 204 0")
        assert health_filter.filter(record) is False

    def test_passes_live_500_error(self, health_filter: HealthCheckFilter) -> None:
        """Failed health checks should still be logged."""
        record = _make_record("uvicorn.access", "GET /health/live HTTP/1.1 500 0")
        assert health_filter.filter(record) is True

    def test_passes_ready_404_error(self, health_filter: HealthCheckFilter) -> None:
        record = _make_record("uvicorn.access", "GET /health/ready HTTP/1.1 404 0")
        assert health_filter.filter(record) is True

    def test_passes_non_health_route_200(self, health_filter: HealthCheckFilter) -> None:
        record = _make_record("uvicorn.access", "GET /api/v1/agents HTTP/1.1 200 42")
        assert health_filter.filter(record) is True

    def test_passes_non_uvicorn_access_logger(self, health_filter: HealthCheckFilter) -> None:
        """Health-check filtering only applies to the uvicorn.access logger."""
        record = _make_record("myapp.server", "GET /health/live HTTP/1.1 200 0")
        assert health_filter.filter(record) is True

    def test_passes_root_logger_record(self, health_filter: HealthCheckFilter) -> None:
        record = _make_record("root", "GET /health/live HTTP/1.1 200 0")
        assert health_filter.filter(record) is True
