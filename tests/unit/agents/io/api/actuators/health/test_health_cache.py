"""Unit tests for HealthCheckCache."""

from unittest.mock import AsyncMock, MagicMock, patch


from blueprint.agents.io.api.actuators.health.health_cache import HealthCheckCache
from blueprint.agents.models.api import ComponentHealth


def _make_provider(status: str, message: str = "ok") -> MagicMock:
    """Return a mock health check provider."""
    provider = MagicMock()
    provider.health_check = AsyncMock(return_value=ComponentHealth(status=status, message=message))
    return provider


class TestHealthCheckCacheInit:
    def test_initial_status_is_up(self) -> None:
        cache = HealthCheckCache()
        assert cache._cached_response.status == "UP"

    def test_custom_initial_status(self) -> None:
        cache = HealthCheckCache(initial_status="DOWN")
        assert cache._cached_response.status == "DOWN"

    def test_no_providers_on_init(self) -> None:
        cache = HealthCheckCache()
        assert cache._health_check_provider is None

    def test_default_interval_is_30(self) -> None:
        cache = HealthCheckCache()
        assert cache.check_interval_seconds == 30


class TestHealthCheckCacheProviderUpdates:
    def test_set_health_check_provider_stores_provider(self) -> None:
        cache = HealthCheckCache()
        provider = {"db": _make_provider("healthy")}
        cache.set_health_check_provider(provider)
        assert cache._health_check_provider is provider


class TestRunHealthChecks:
    async def test_all_healthy_providers_yield_up_status(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_check_provider(
            {
                "db": _make_provider("healthy"),
                "nats": _make_provider("healthy"),
            }
        )
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.status == "UP"

    async def test_one_unhealthy_provider_yields_down_status(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_check_provider(
            {
                "db": _make_provider("healthy"),
                "nats": _make_provider("unhealthy", "timeout"),
            }
        )
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.status == "DOWN"

    async def test_all_unhealthy_yields_down_status(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_check_provider(
            {
                "db": _make_provider("unhealthy"),
            }
        )
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.status == "DOWN"

    async def test_components_populated_after_run(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_check_provider({"db": _make_provider("healthy")})
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert "db" in result.components

    async def test_exception_in_provider_marks_component_unhealthy(self) -> None:
        provider = MagicMock()
        provider.health_check = AsyncMock(side_effect=RuntimeError("boom"))
        cache = HealthCheckCache()
        cache.set_health_check_provider({"flaky": provider})
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.components["flaky"].status == "unhealthy"

    async def test_exception_message_included_in_component_health(self) -> None:
        provider = MagicMock()
        provider.health_check = AsyncMock(side_effect=RuntimeError("connection refused"))
        cache = HealthCheckCache()
        cache.set_health_check_provider({"svc": provider})
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert "connection refused" in result.components["svc"].message

    async def test_no_op_when_no_providers_configured(self) -> None:
        cache = HealthCheckCache()
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.status == "UP"  # initial value unchanged


class TestHealthCheckCacheMetadata:
    def test_get_cache_age_seconds_returns_non_negative(self) -> None:
        cache = HealthCheckCache()
        assert cache.get_cache_age_seconds() >= 0.0

    def test_get_cache_info_contains_required_keys(self) -> None:
        cache = HealthCheckCache()
        info = cache.get_cache_info()
        for key in ("last_update", "age_seconds", "check_interval_seconds", "status", "components_count"):
            assert key in info

    def test_get_cache_info_status_matches_cached_response(self) -> None:
        cache = HealthCheckCache()
        assert cache.get_cache_info()["status"] == cache._cached_response.status


class TestHealthCheckCacheStartStop:
    async def test_start_runs_initial_check(self) -> None:
        cache = HealthCheckCache(check_interval_seconds=3600)
        provider = _make_provider("healthy")
        cache.set_health_check_provider({"svc": provider})
        with patch("blueprint.agents.io.api.actuators.health.health_cache.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched
            await cache.start()
        provider.health_check.assert_awaited_once()
        await cache.stop()

    async def test_start_is_idempotent(self) -> None:
        cache = HealthCheckCache(check_interval_seconds=3600)
        with patch("blueprint.agents.io.api.actuators.health.health_cache.AsyncIOScheduler") as mock_scheduler_cls:
            mock_sched = MagicMock()
            mock_scheduler_cls.return_value = mock_sched
            await cache.start()
            await cache.start()  # second call is a no-op
        mock_scheduler_cls.assert_called_once()
        await cache.stop()

    async def test_stop_is_safe_when_not_started(self) -> None:
        cache = HealthCheckCache()
        await cache.stop()  # must not raise
