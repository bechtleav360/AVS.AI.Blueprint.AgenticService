"""Unit tests for RedisCacheService."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService


@pytest.fixture
def redis_cache_service(mock_registry, mock_config) -> Generator[RedisCacheService]:
    """RedisCacheService backed by an in-memory fakeredis client."""
    svc = RedisCacheService.__new__(RedisCacheService)
    svc._client = fakeredis.FakeRedis(decode_responses=True)
    svc._key_prefix = ""
    svc._default_ttl = None
    svc._fallback_to_local = False
    svc._redis_url = "redis://fake:6379/0"
    svc._password = None
    svc._db = 0
    svc._tls = False
    yield svc
    svc._client.close()


@pytest.fixture
def prefixed_redis_cache_service(mock_registry, mock_config) -> Generator[RedisCacheService]:
    """RedisCacheService with a non-empty key_prefix."""
    svc = RedisCacheService.__new__(RedisCacheService)
    svc._client = fakeredis.FakeRedis(decode_responses=True)
    svc._key_prefix = "service-a"
    svc._default_ttl = None
    svc._fallback_to_local = False
    svc._redis_url = "redis://fake:6379/0"
    svc._password = None
    svc._db = 0
    svc._tls = False
    yield svc
    svc._client.close()


# ---------------------------------------------------------------------------
# set / get
# ---------------------------------------------------------------------------


class TestSetAndGet:
    def test_get_returns_stored_value(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("key", "value")
        assert redis_cache_service.get("key") == "value"

    def test_get_missing_key_returns_none(self, redis_cache_service: RedisCacheService) -> None:
        assert redis_cache_service.get("nonexistent") is None

    def test_namespace_isolates_keys(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("k", "ns-a-value", namespace="ns-a")
        redis_cache_service.set("k", "ns-b-value", namespace="ns-b")
        assert redis_cache_service.get("k", namespace="ns-a") == "ns-a-value"
        assert redis_cache_service.get("k", namespace="ns-b") == "ns-b-value"

    def test_dict_key_stored_and_retrieved(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set({"user": "alice", "role": "admin"}, {"data": 1})
        result = redis_cache_service.get({"user": "alice", "role": "admin"})
        assert result == {"data": 1}

    def test_list_key_stored_and_retrieved(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set(["b", "a"], "sorted-val")
        assert redis_cache_service.get(["a", "b"]) == "sorted-val"

    def test_complex_value_round_trip(self, redis_cache_service: RedisCacheService) -> None:
        payload = {"items": [1, 2, 3], "meta": {"score": 0.5}}
        redis_cache_service.set("complex", payload)
        assert redis_cache_service.get("complex") == payload

    def test_key_prefix_is_applied(self, prefixed_redis_cache_service: RedisCacheService) -> None:
        prefixed_redis_cache_service.set("k", "v", namespace="ns")
        full_key = prefixed_redis_cache_service._full_key("k", "ns")
        assert full_key.startswith("service-a:ns:")
        assert prefixed_redis_cache_service._client.get(full_key) is not None


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_existing_key_returns_true(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("key", "val")
        assert redis_cache_service.delete("key") is True

    def test_deleted_key_no_longer_retrievable(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("key", "val")
        redis_cache_service.delete("key")
        assert redis_cache_service.get("key") is None

    def test_delete_nonexistent_key_returns_false(self, redis_cache_service: RedisCacheService) -> None:
        assert redis_cache_service.delete("ghost") is False


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


class TestExists:
    def test_true_after_set(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("key", "val")
        assert redis_cache_service.exists("key") is True

    def test_false_before_set(self, redis_cache_service: RedisCacheService) -> None:
        assert redis_cache_service.exists("missing") is False

    def test_false_after_delete(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("key", "val")
        redis_cache_service.delete("key")
        assert redis_cache_service.exists("key") is False


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_namespace_removes_only_that_namespace(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("k", "v", namespace="ns-a")
        redis_cache_service.set("k", "v", namespace="ns-b")
        redis_cache_service.clear(namespace="ns-a")
        assert redis_cache_service.get("k", namespace="ns-a") is None
        assert redis_cache_service.get("k", namespace="ns-b") == "v"

    def test_clear_all_removes_everything(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("k1", "v1", namespace="ns-a")
        redis_cache_service.set("k2", "v2", namespace="ns-b")
        redis_cache_service.clear()
        assert redis_cache_service.get("k1", namespace="ns-a") is None
        assert redis_cache_service.get("k2", namespace="ns-b") is None

    def test_clear_with_prefix_only_clears_own_prefix(self, prefixed_redis_cache_service: RedisCacheService) -> None:
        prefixed_redis_cache_service.set("k", "v", namespace="ns")
        prefixed_redis_cache_service._client.set("other-service:ns:foo", "untouched")
        prefixed_redis_cache_service.clear()
        assert prefixed_redis_cache_service._client.get("other-service:ns:foo") == "untouched"


# ---------------------------------------------------------------------------
# TTL expiration — Redis enforces TTL natively via EX
# ---------------------------------------------------------------------------


class TestTtl:
    def test_expired_entry_returns_none(self, redis_cache_service: RedisCacheService) -> None:
        with patch("time.time", return_value=1000.0):
            redis_cache_service.set("key", "value", ttl=60)
        with patch("time.time", return_value=1100.0):
            result = redis_cache_service.get("key")
        assert result is None

    def test_non_expired_entry_still_returned(self, redis_cache_service: RedisCacheService) -> None:
        with patch("time.time", return_value=1000.0):
            redis_cache_service.set("key", "value", ttl=60)
        with patch("time.time", return_value=1050.0):
            result = redis_cache_service.get("key")
        assert result == "value"

    def test_expired_key_reports_not_existing(self, redis_cache_service: RedisCacheService) -> None:
        with patch("time.time", return_value=1000.0):
            redis_cache_service.set("key", "value", ttl=60)
        with patch("time.time", return_value=1100.0):
            assert redis_cache_service.exists("key") is False

    def test_default_ttl_used_when_not_specified(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service._default_ttl = 30
        redis_cache_service.set("key", "value")
        full_key = redis_cache_service._full_key("key", "default")
        ttl = redis_cache_service._client.ttl(full_key)
        assert 0 < ttl <= 30

    def test_no_ttl_set_when_default_is_none(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("key", "value")
        full_key = redis_cache_service._full_key("key", "default")
        # -1 => key exists but has no TTL
        assert redis_cache_service._client.ttl(full_key) == -1


# ---------------------------------------------------------------------------
# hash
# ---------------------------------------------------------------------------


class TestHash:
    def test_same_string_produces_same_hash(self, redis_cache_service: RedisCacheService) -> None:
        assert redis_cache_service.hash("hello") == redis_cache_service.hash("hello")

    def test_different_strings_produce_different_hashes(self, redis_cache_service: RedisCacheService) -> None:
        assert redis_cache_service.hash("hello") != redis_cache_service.hash("world")

    def test_list_order_does_not_affect_hash(self, redis_cache_service: RedisCacheService) -> None:
        assert redis_cache_service.hash(["a", "b", "c"]) == redis_cache_service.hash(["c", "a", "b"])

    def test_dict_key_order_does_not_affect_hash(self, redis_cache_service: RedisCacheService) -> None:
        assert redis_cache_service.hash({"b": 2, "a": 1}) == redis_cache_service.hash({"a": 1, "b": 2})


# ---------------------------------------------------------------------------
# list_namespaces / list_values / get_stats
# ---------------------------------------------------------------------------


class TestListAndStats:
    def test_list_namespaces_includes_populated_namespaces(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("k", "v", namespace="alpha")
        redis_cache_service.set("k", "v", namespace="beta")
        namespaces = redis_cache_service.list_namespaces()
        assert "alpha" in namespaces
        assert "beta" in namespaces

    def test_list_namespaces_with_prefix(self, prefixed_redis_cache_service: RedisCacheService) -> None:
        prefixed_redis_cache_service.set("k", "v", namespace="alpha")
        prefixed_redis_cache_service._client.set("other:beta:foo", "should-not-show")
        namespaces = prefixed_redis_cache_service.list_namespaces()
        assert "alpha" in namespaces
        assert "beta" not in namespaces

    def test_list_values_returns_stored_values(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service.set("k1", "val-a", namespace="ns")
        redis_cache_service.set("k2", "val-b", namespace="ns")
        values = list(redis_cache_service.list_values(namespace="ns"))
        assert "val-a" in values
        assert "val-b" in values

    def test_list_values_respects_limit(self, redis_cache_service: RedisCacheService) -> None:
        for i in range(5):
            redis_cache_service.set(f"k{i}", f"v{i}", namespace="ns")
        values = list(redis_cache_service.list_values(namespace="ns", limit=2))
        assert len(values) == 2

    def test_get_stats_has_expected_fields(self, redis_cache_service: RedisCacheService) -> None:
        # fakeredis does not implement INFO, so substitute a deterministic value.
        with patch.object(
            redis_cache_service._client,
            "info",
            return_value={
                "redis_version": "7.0.0",
                "connected_clients": 1,
                "used_memory_human": "1.0M",
                "uptime_in_seconds": 42,
            },
        ):
            stats = redis_cache_service.get_stats()
        assert stats["backend"] == "redis"
        assert "key_prefix" in stats
        assert "redis_url" in stats
        assert stats["redis_version"] == "7.0.0"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_calls_ping(self, redis_cache_service: RedisCacheService) -> None:
        with patch.object(redis_cache_service._client, "ping") as mock_ping:
            await redis_cache_service.on_startup()
        mock_ping.assert_called_once()

    async def test_on_startup_raises_when_no_fallback(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service._fallback_to_local = False
        with patch.object(redis_cache_service._client, "ping", side_effect=ConnectionError("boom")):
            with pytest.raises(ConnectionError):
                await redis_cache_service.on_startup()

    async def test_on_startup_swallows_when_fallback_enabled(self, redis_cache_service: RedisCacheService) -> None:
        redis_cache_service._fallback_to_local = True
        with patch.object(redis_cache_service._client, "ping", side_effect=ConnectionError("boom")):
            await redis_cache_service.on_startup()  # must not raise

    async def test_on_shutdown_calls_close(self, redis_cache_service: RedisCacheService) -> None:
        with patch.object(redis_cache_service, "close") as mock_close:
            await redis_cache_service.on_shutdown()
        mock_close.assert_called_once()

    def test_close_calls_client_close(self, redis_cache_service: RedisCacheService) -> None:
        mock_client = MagicMock()
        redis_cache_service._client = mock_client
        redis_cache_service.close()
        mock_client.close.assert_called_once()
