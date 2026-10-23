"""Unit tests for HealthCheckFilter."""

import logging

import pytest

from blueprint.agents.config.custom_logging import HealthCheckFilter

UVICORN_ACCESS_FORMAT = '%s - "%s %s HTTP/%s" %d'
"""The format string uvicorn's h11 and httptools protocols pass to ``uvicorn.access``.

The records below are built the way uvicorn builds them. The previous tests used an invented
format (``GET /health/live HTTP/1.1 200 0``) that the old substring check happened to match,
while uvicorn's real line -- which ends with the status code -- never did.
"""


def _access_record(path: str, status: int, method: str = "GET", name: str = "uvicorn.access") -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=UVICORN_ACCESS_FORMAT,
        args=("10.0.0.1:51234", method, path, "1.1", status),
        exc_info=None,
    )


class TestHealthCheckFilter:
    @pytest.fixture
    def health_filter(self) -> HealthCheckFilter:
        return HealthCheckFilter()

    def test_record_renders_as_uvicorn_does(self) -> None:
        """Guards the fixture: the status code ends the line, with nothing after it."""
        assert _access_record("/health/ready", 200).getMessage() == '10.0.0.1:51234 - "GET /health/ready HTTP/1.1" 200'

    @pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
    @pytest.mark.parametrize("status", [200, 204])
    def test_drops_successful_probe(self, health_filter: HealthCheckFilter, path: str, status: int) -> None:
        assert health_filter.filter(_access_record(path, status)) is False

    def test_drops_successful_probe_with_query_string(self, health_filter: HealthCheckFilter) -> None:
        assert health_filter.filter(_access_record("/health/ready?probe=k8s", 200)) is False

    def test_drops_successful_probe_under_route_prefix(self, health_filter: HealthCheckFilter) -> None:
        assert health_filter.filter(_access_record("/svc/health/live", 200)) is False

    @pytest.mark.parametrize("status", [307, 404, 500, 503])
    def test_keeps_unsuccessful_probe(self, health_filter: HealthCheckFilter, status: int) -> None:
        """A probe that did not succeed is exactly what the access log is read for."""
        assert health_filter.filter(_access_record("/health/ready", status)) is True

    @pytest.mark.parametrize("path", ["/api/v1/agents", "/health", "/health/live/extra", "/status/env"])
    def test_keeps_other_routes(self, health_filter: HealthCheckFilter, path: str) -> None:
        assert health_filter.filter(_access_record(path, 200)) is True

    def test_keeps_health_path_only_in_query_string(self, health_filter: HealthCheckFilter) -> None:
        assert health_filter.filter(_access_record("/api/v1/redirect?to=/health/live", 200)) is True

    @pytest.mark.parametrize("name", ["myapp.server", "root", "uvicorn.error"])
    def test_keeps_records_of_other_loggers(self, health_filter: HealthCheckFilter, name: str) -> None:
        """Health-check filtering only applies to the uvicorn.access logger."""
        assert health_filter.filter(_access_record("/health/live", 200, name=name)) is True

    def test_keeps_unparseable_access_line(self, health_filter: HealthCheckFilter) -> None:
        """A format uvicorn might change to costs log volume, never a lost failure line."""
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "GET /health/live 200", (), None)
        assert health_filter.filter(record) is True
