"""Unit tests for HealthCheckCache."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from blueprint.agents.io.api.actuators.health.health_base import HealthCheckEntry
from blueprint.agents.io.api.actuators.health.health_cache import HealthCheckCache
from blueprint.agents.io.api.actuators.health.readiness_policy import ReadinessPolicy
from blueprint.agents.models.api import ComponentHealth


def _make_provider(status: str, message: str = "ok") -> MagicMock:
    """Return a mock health check provider."""
    provider = MagicMock()
    provider.health_check = AsyncMock(return_value=ComponentHealth(status=status, message=message))
    return provider


def _entry(name: str, status: str, message: str = "ok", namespace: str = "") -> HealthCheckEntry:
    """A registered check: the checker plus the agent it belongs to."""
    return HealthCheckEntry(name=name, namespace=namespace, checker=_make_provider(status, message))


class TestHealthCheckCacheInit:
    def test_initial_status_is_up(self) -> None:
        cache = HealthCheckCache()
        assert cache._cached_response.status == "UP"

    def test_custom_initial_status(self) -> None:
        cache = HealthCheckCache(initial_status="DOWN")
        assert cache._cached_response.status == "DOWN"

    def test_no_providers_on_init(self) -> None:
        cache = HealthCheckCache()
        assert cache._entries == ()

    def test_default_interval_is_30(self) -> None:
        cache = HealthCheckCache()
        assert cache.check_interval_seconds == 30


class TestHealthCheckCacheProviderUpdates:
    def test_set_health_entries_stores_them(self) -> None:
        cache = HealthCheckCache()
        entry = _entry("db", "healthy")
        cache.set_health_entries([entry])
        assert cache._entries == (entry,)

    def test_setting_again_replaces_the_whole_set(self) -> None:
        """ActuatorApi accumulates and re-pushes, so this object holds one authoritative list."""
        cache = HealthCheckCache()
        cache.set_health_entries([_entry("db", "healthy")])
        second = _entry("nats", "healthy")
        cache.set_health_entries([second])
        assert cache._entries == (second,)


class TestRunHealthChecks:
    async def test_all_healthy_providers_yield_up_status(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_entries([_entry("db", "healthy"), _entry("nats", "healthy")])
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.status == "UP"

    async def test_one_unhealthy_provider_yields_down_status(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_entries([_entry("db", "healthy"), _entry("nats", "unhealthy", "timeout")])
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.status == "DOWN"

    async def test_all_unhealthy_yields_down_status(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_entries([_entry("db", "unhealthy")])
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.status == "DOWN"

    async def test_components_populated_after_run(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_entries([_entry("db", "healthy")])
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert "db" in result.components

    async def test_exception_in_provider_marks_component_unhealthy(self) -> None:
        provider = MagicMock()
        provider.health_check = AsyncMock(side_effect=RuntimeError("boom"))
        cache = HealthCheckCache()
        cache.set_health_entries([HealthCheckEntry(name="flaky", namespace="", checker=provider)])
        await cache._run_health_checks()
        result = await cache.get_health_status()
        assert result.components["flaky"].status == "unhealthy"

    async def test_exception_message_included_in_component_health(self) -> None:
        provider = MagicMock()
        provider.health_check = AsyncMock(side_effect=RuntimeError("connection refused"))
        cache = HealthCheckCache()
        cache.set_health_entries([HealthCheckEntry(name="svc", namespace="", checker=provider)])
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
        cache.set_health_entries([HealthCheckEntry(name="svc", namespace="", checker=provider)])
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


class TestAnEntryIsAttributedToItsAgent:
    """D4: the payload key is a rendering; the agent is carried as data beside it."""

    async def test_the_root_keeps_the_bare_name(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_entries([_entry("db", "healthy")])
        await cache._run_health_checks()
        assert "db" in (await cache.get_health_status()).components

    async def test_an_agents_check_is_prefixed(self) -> None:
        cache = HealthCheckCache()
        cache.set_health_entries([_entry("db", "healthy", namespace="orders")])
        await cache._run_health_checks()
        assert "orders.db" in (await cache.get_health_status()).components

    async def test_two_agents_declaring_one_name_are_two_components(self) -> None:
        """A dict of name -> checker lost one of these, silently."""
        cache = HealthCheckCache()
        cache.set_health_entries(
            [
                _entry("db", "healthy", namespace="orders"),
                _entry("db", "unhealthy", "down", namespace="billing"),
            ]
        )
        await cache._run_health_checks()

        components = (await cache.get_health_status()).components
        assert set(components) == {"orders.db", "billing.db"}
        assert (components["orders.db"].status, components["billing.db"].status) == ("healthy", "unhealthy")

    async def test_a_failure_is_logged_with_its_agent(self, caplog: pytest.LogCaptureFixture) -> None:
        """Whose check is failing is the question asked of a group, not only which one."""
        provider = MagicMock()
        provider.health_check = AsyncMock(side_effect=RuntimeError("boom"))
        cache = HealthCheckCache()
        cache.set_health_entries([HealthCheckEntry(name="db", namespace="orders", checker=provider)])

        with caplog.at_level("WARNING", logger="blueprint.agents.io.api.actuators.health.health_cache"):
            await cache._run_health_checks()

        assert "Health check 'db' of agent 'orders' failed" in caplog.text

    def test_the_root_agent_is_named_where_a_value_is_required(self) -> None:
        assert (_entry("db", "healthy").agent, _entry("db", "healthy", namespace="orders").agent) == ("<root>", "orders")


class TestTheVerdictIsPerAgent:
    """C3: the overall status is no longer a fold over every check, but a policy over agents."""

    @staticmethod
    def _supervisor(namespaces: list[str], critical: set[str]) -> MagicMock:
        """A stand-in supervisor: the cache reads its namespaces and its critical set."""
        supervisor = MagicMock()
        supervisor.status = dict.fromkeys(namespaces, True)
        supervisor.critical_namespaces = frozenset(critical)
        supervisor.observe = AsyncMock()
        return supervisor

    @staticmethod
    def _entries() -> list[HealthCheckEntry]:
        return [
            _entry("cache", "healthy", namespace="orders"),
            _entry("cache", "unhealthy", "redis is gone", namespace="billing"),
        ]

    async def _run(self, policy: ReadinessPolicy, critical: set[str]) -> HealthCheckCache:
        supervisor = self._supervisor(["", "orders", "billing"], critical)
        cache = HealthCheckCache(policy=policy, supervisor=supervisor)
        cache.set_health_entries(self._entries())
        await cache._run_health_checks()
        return cache

    async def test_all_takes_the_pod_out_for_one_degraded_agent(self) -> None:
        cache = await self._run(ReadinessPolicy.ALL, set())
        assert (await cache.get_health_status()).status == "DOWN"

    async def test_critical_keeps_the_pod_in_for_an_agent_nobody_flagged(self) -> None:
        cache = await self._run(ReadinessPolicy.CRITICAL, {"orders"})
        assert (await cache.get_health_status()).status == "UP"

    async def test_the_payload_says_which_agent_is_down(self) -> None:
        """A pod answering UP with a failing check in it has to explain itself."""
        cache = await self._run(ReadinessPolicy.CRITICAL, {"orders"})
        response = await cache.get_health_status()
        assert response.policy == "critical"
        assert response.namespaces["billing"].status == "DOWN"
        assert response.namespaces["billing"].failing == ["billing.cache"]
        assert response.namespaces["billing"].critical is False
        assert response.namespaces["orders"].status == "UP"

    async def test_the_root_is_always_reported_as_critical(self) -> None:
        cache = await self._run(ReadinessPolicy.CRITICAL, {"orders"})
        assert (await cache.get_health_status()).namespaces["<root>"].critical is True

    async def test_an_agent_with_no_checks_is_still_in_the_payload(self) -> None:
        """Leaving it out would make 'any' and 'critical' read a shorter list than the group has."""
        supervisor = self._supervisor(["", "orders", "quiet"], set())
        cache = HealthCheckCache(policy=ReadinessPolicy.ANY, supervisor=supervisor)
        cache.set_health_entries([_entry("cache", "healthy", namespace="orders")])
        await cache._run_health_checks()
        assert (await cache.get_health_status()).namespaces["quiet"].status == "UP"

    async def test_the_supervisor_is_told_every_agents_verdict(self) -> None:
        """It is what emits the C7 signal and stops a degraded agent consuming."""
        supervisor = self._supervisor(["", "orders", "billing"], set())
        cache = HealthCheckCache(supervisor=supervisor)
        cache.set_health_entries(self._entries())
        await cache._run_health_checks()
        supervisor.observe.assert_awaited_once_with({"": True, "orders": True, "billing": False})

    async def test_the_agent_comes_from_the_entry_not_from_the_key(self) -> None:
        """Splitting 'orders.cache:v2.sessions' on a dot attributes it to the wrong agent."""
        supervisor = self._supervisor(["", "orders"], set())
        cache = HealthCheckCache(supervisor=supervisor)
        cache.set_health_entries([_entry("cache:v2.sessions", "unhealthy", "gone", namespace="orders")])
        await cache._run_health_checks()
        supervisor.observe.assert_awaited_once_with({"": True, "orders": False})

    async def test_a_cache_with_no_supervisor_still_answers(self) -> None:
        """Nothing about the caching behaviour depends on a metrics pipeline or a registry."""
        cache = HealthCheckCache()
        cache.set_health_entries(self._entries())
        await cache._run_health_checks()
        assert (await cache.get_health_status()).status == "DOWN"
