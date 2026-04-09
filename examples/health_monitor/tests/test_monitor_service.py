"""Unit tests for MonitorService."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.schemas import EndpointConfig, HealthResult
from src.services.monitor_service import MonitorService


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create a mock cache service that behaves like a simple dict store."""
    cache = MagicMock()
    store: dict[str, Any] = {}

    def _get(key: str, namespace: str = "default") -> Any | None:
        return store.get(f"{namespace}:{key}")

    def _set(key: str, value: Any, namespace: str = "default", ttl: int | None = None) -> None:
        store[f"{namespace}:{key}"] = value

    cache.get = MagicMock(side_effect=_get)
    cache.set = MagicMock(side_effect=_set)
    return cache


@pytest.fixture
def service(mock_cache: MagicMock) -> MonitorService:
    """Create a MonitorService with mock cache and sample endpoints."""
    svc = MonitorService.__new__(MonitorService)
    svc._cache = mock_cache
    svc._check_timeout = 10
    svc._endpoints = [
        EndpointConfig(name="httpbin", url="https://httpbin.org/status/200"),
        EndpointConfig(name="jsonplaceholder", url="https://jsonplaceholder.typicode.com/posts/1"),
    ]
    return svc


@pytest.fixture
def sample_endpoint() -> EndpointConfig:
    return EndpointConfig(name="httpbin", url="https://httpbin.org/status/200")


class TestCheckEndpoint:
    @pytest.mark.asyncio
    async def test_check_endpoint_healthy(self, service: MonitorService, sample_endpoint: EndpointConfig) -> None:
        """A 200 response should produce a healthy result."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.services.monitor_service.httpx.AsyncClient", return_value=mock_client):
            result = await service.check_endpoint(sample_endpoint)

        assert result.healthy is True
        assert result.status_code == 200
        assert result.endpoint_name == "httpbin"
        assert result.response_time_ms is not None
        assert result.error is None

    @pytest.mark.asyncio
    async def test_check_endpoint_server_error(self, service: MonitorService, sample_endpoint: EndpointConfig) -> None:
        """A 500 response should produce an unhealthy result."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.services.monitor_service.httpx.AsyncClient", return_value=mock_client):
            result = await service.check_endpoint(sample_endpoint)

        assert result.healthy is False
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_check_endpoint_connection_error(self, service: MonitorService, sample_endpoint: EndpointConfig) -> None:
        """A connection error should produce an unhealthy result with error detail."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.services.monitor_service.httpx.AsyncClient", return_value=mock_client):
            result = await service.check_endpoint(sample_endpoint)

        assert result.healthy is False
        assert result.status_code is None
        assert result.response_time_ms is None
        assert "Connection refused" in (result.error or "")


class TestStoreResult:
    @pytest.mark.asyncio
    async def test_store_healthy_result(self, service: MonitorService, mock_cache: MagicMock) -> None:
        """Storing a healthy result should reset consecutive failures and update uptime."""
        result = HealthResult(
            endpoint_name="httpbin",
            url="https://httpbin.org/status/200",
            status_code=200,
            response_time_ms=42.0,
            healthy=True,
            error=None,
            checked_at="2026-01-01T00:00:00+00:00",
        )
        await service.store_result(result)

        # Verify cache was called to store the status
        mock_cache.set.assert_called()
        stored_calls = [call for call in mock_cache.set.call_args_list if call[0][0].startswith("status:")]
        assert len(stored_calls) > 0

    @pytest.mark.asyncio
    async def test_store_unhealthy_result_increments_failures(self, service: MonitorService, mock_cache: MagicMock) -> None:
        """Storing an unhealthy result should increment consecutive failures."""
        result = HealthResult(
            endpoint_name="httpbin",
            url="https://httpbin.org/status/200",
            status_code=None,
            response_time_ms=None,
            healthy=False,
            error="timeout",
            checked_at="2026-01-01T00:00:00+00:00",
        )
        await service.store_result(result)
        await service.store_result(result)

        # Retrieve the stored status
        status = await service.get_endpoint_status("httpbin")
        assert status is not None
        assert status.consecutive_failures == 2
        assert status.total_checks == 2


class TestGetEndpointStatus:
    @pytest.mark.asyncio
    async def test_get_status_not_found(self, service: MonitorService) -> None:
        """Requesting a status for an endpoint with no checks should return None."""
        status = await service.get_endpoint_status("nonexistent")
        assert status is None

    @pytest.mark.asyncio
    async def test_get_status_after_store(self, service: MonitorService) -> None:
        """After storing a result, get_endpoint_status should return valid data."""
        result = HealthResult(
            endpoint_name="httpbin",
            url="https://httpbin.org/status/200",
            status_code=200,
            response_time_ms=15.0,
            healthy=True,
            error=None,
            checked_at="2026-01-01T00:00:00+00:00",
        )
        await service.store_result(result)

        status = await service.get_endpoint_status("httpbin")
        assert status is not None
        assert status.endpoint_name == "httpbin"
        assert status.total_checks == 1
        assert status.uptime_percentage == 100.0


class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_report_with_no_checks(self, service: MonitorService) -> None:
        """Report with no prior checks should list all endpoints with default status."""
        report = await service.generate_report()
        assert len(report.endpoints) == 2
        assert report.generated_at is not None

    @pytest.mark.asyncio
    async def test_report_overall_healthy(self, service: MonitorService) -> None:
        """Report should be overall_healthy when all endpoints are healthy."""
        for ep in service._endpoints:
            result = HealthResult(
                endpoint_name=ep.name,
                url=ep.url,
                status_code=200,
                response_time_ms=10.0,
                healthy=True,
                error=None,
                checked_at="2026-01-01T00:00:00+00:00",
            )
            await service.store_result(result)

        report = await service.generate_report()
        assert report.overall_healthy is True

    @pytest.mark.asyncio
    async def test_report_overall_unhealthy(self, service: MonitorService) -> None:
        """Report should be overall_healthy=False when any endpoint is unhealthy."""
        healthy = HealthResult(
            endpoint_name="httpbin",
            url="https://httpbin.org/status/200",
            status_code=200,
            response_time_ms=10.0,
            healthy=True,
            error=None,
            checked_at="2026-01-01T00:00:00+00:00",
        )
        unhealthy = HealthResult(
            endpoint_name="jsonplaceholder",
            url="https://jsonplaceholder.typicode.com/posts/1",
            status_code=500,
            response_time_ms=100.0,
            healthy=False,
            error=None,
            checked_at="2026-01-01T00:00:00+00:00",
        )
        await service.store_result(healthy)
        await service.store_result(unhealthy)

        report = await service.generate_report()
        assert report.overall_healthy is False
