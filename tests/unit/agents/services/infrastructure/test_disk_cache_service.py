"""Unit tests for DiskCacheService."""

from unittest.mock import patch

import pytest

from blueprint.agents.services.infrastructure.cache_service import DiskCacheService

_TIME_MODULE = "blueprint.agents.services.infrastructure.cache_service.time"


@pytest.fixture
def cache_service(tmp_path, mock_registry, mock_config) -> DiskCacheService:
    """DiskCacheService backed by a temp directory."""
    svc = DiskCacheService(cache_dir=str(tmp_path / "cache"))
    yield svc
    svc.close()


# ---------------------------------------------------------------------------
# set / get
# ---------------------------------------------------------------------------


class TestSetAndGet:
    def test_get_returns_stored_value(self, cache_service: DiskCacheService) -> None:
        cache_service.set("key", "value")
        assert cache_service.get("key") == "value"

    def test_get_missing_key_returns_none(self, cache_service: DiskCacheService) -> None:
        assert cache_service.get("nonexistent") is None

    def test_namespace_isolates_keys(self, cache_service: DiskCacheService) -> None:
        cache_service.set("k", "ns-a-value", namespace="ns-a")
        cache_service.set("k", "ns-b-value", namespace="ns-b")
        assert cache_service.get("k", namespace="ns-a") == "ns-a-value"
        assert cache_service.get("k", namespace="ns-b") == "ns-b-value"

    def test_dict_key_stored_and_retrieved(self, cache_service: DiskCacheService) -> None:
        cache_service.set({"user": "alice", "role": "admin"}, {"data": 1})
        result = cache_service.get({"user": "alice", "role": "admin"})
        assert result == {"data": 1}

    def test_list_key_stored_and_retrieved(self, cache_service: DiskCacheService) -> None:
        cache_service.set(["b", "a"], "sorted-val")
        assert cache_service.get(["a", "b"]) == "sorted-val"


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    def test_delete_existing_key_returns_true(self, cache_service: DiskCacheService) -> None:
        cache_service.set("key", "val")
        assert cache_service.delete("key") is True

    def test_deleted_key_no_longer_retrievable(self, cache_service: DiskCacheService) -> None:
        cache_service.set("key", "val")
        cache_service.delete("key")
        assert cache_service.get("key") is None

    def test_delete_nonexistent_key_returns_false(self, cache_service: DiskCacheService) -> None:
        assert cache_service.delete("ghost") is False


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


class TestExists:
    def test_true_after_set(self, cache_service: DiskCacheService) -> None:
        cache_service.set("key", "val")
        assert cache_service.exists("key") is True

    def test_false_before_set(self, cache_service: DiskCacheService) -> None:
        assert cache_service.exists("missing") is False

    def test_false_after_delete(self, cache_service: DiskCacheService) -> None:
        cache_service.set("key", "val")
        cache_service.delete("key")
        assert cache_service.exists("key") is False


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_namespace_removes_only_that_namespace(self, cache_service: DiskCacheService) -> None:
        cache_service.set("k", "v", namespace="ns-a")
        cache_service.set("k", "v", namespace="ns-b")
        cache_service.clear(namespace="ns-a")
        assert cache_service.get("k", namespace="ns-a") is None
        assert cache_service.get("k", namespace="ns-b") == "v"

    def test_clear_all_removes_everything(self, cache_service: DiskCacheService) -> None:
        cache_service.set("k1", "v1", namespace="ns-a")
        cache_service.set("k2", "v2", namespace="ns-b")
        cache_service.clear()
        assert cache_service.get("k1", namespace="ns-a") is None
        assert cache_service.get("k2", namespace="ns-b") is None


# ---------------------------------------------------------------------------
# TTL expiration
# ---------------------------------------------------------------------------


class TestTtl:
    def test_expired_entry_returns_none(self, cache_service: DiskCacheService) -> None:
        with patch(f"{_TIME_MODULE}.time") as mock_time:
            mock_time.return_value = 1000.0
            cache_service.set("key", "value", ttl=60)
            mock_time.return_value = 1100.0  # 100 s later — beyond TTL
            result = cache_service.get("key")
        assert result is None

    def test_non_expired_entry_still_returned(self, cache_service: DiskCacheService) -> None:
        with patch(f"{_TIME_MODULE}.time") as mock_time:
            mock_time.return_value = 1000.0
            cache_service.set("key", "value", ttl=60)
            mock_time.return_value = 1050.0  # 50 s later — within TTL
            result = cache_service.get("key")
        assert result == "value"

    def test_expired_key_reports_not_existing(self, cache_service: DiskCacheService) -> None:
        with patch(f"{_TIME_MODULE}.time") as mock_time:
            mock_time.return_value = 1000.0
            cache_service.set("key", "value", ttl=60)
            mock_time.return_value = 1100.0
            exists = cache_service.exists("key")
        assert exists is False


class TestDefaultTtl:
    def test_default_ttl_applied_when_set_omits_ttl(self, tmp_path, mock_registry, mock_config) -> None:
        svc = DiskCacheService(cache_dir=str(tmp_path / "cache"), default_ttl=60)
        try:
            with patch(f"{_TIME_MODULE}.time") as mock_time:
                mock_time.return_value = 1000.0
                svc.set("key", "value")  # no explicit ttl → falls back to default_ttl
                mock_time.return_value = 1100.0  # beyond default_ttl
                assert svc.get("key") is None
        finally:
            svc.close()

    def test_explicit_ttl_overrides_default_ttl(self, tmp_path, mock_registry, mock_config) -> None:
        svc = DiskCacheService(cache_dir=str(tmp_path / "cache"), default_ttl=10)
        try:
            with patch(f"{_TIME_MODULE}.time") as mock_time:
                mock_time.return_value = 1000.0
                svc.set("key", "value", ttl=120)  # explicit ttl beats default
                mock_time.return_value = 1050.0  # past default_ttl but inside explicit
                assert svc.get("key") == "value"
        finally:
            svc.close()

    def test_no_default_ttl_means_no_expiration(self, cache_service: DiskCacheService) -> None:
        # Fixture is constructed without default_ttl; values must persist.
        with patch(f"{_TIME_MODULE}.time") as mock_time:
            mock_time.return_value = 1000.0
            cache_service.set("key", "value")
            mock_time.return_value = 10_000_000.0
            assert cache_service.get("key") == "value"


# ---------------------------------------------------------------------------
# hash
# ---------------------------------------------------------------------------


class TestHash:
    def test_same_string_produces_same_hash(self, cache_service: DiskCacheService) -> None:
        assert cache_service.hash("hello") == cache_service.hash("hello")

    def test_different_strings_produce_different_hashes(self, cache_service: DiskCacheService) -> None:
        assert cache_service.hash("hello") != cache_service.hash("world")

    def test_list_order_does_not_affect_hash(self, cache_service: DiskCacheService) -> None:
        assert cache_service.hash(["a", "b", "c"]) == cache_service.hash(["c", "a", "b"])

    def test_dict_key_order_does_not_affect_hash(self, cache_service: DiskCacheService) -> None:
        assert cache_service.hash({"b": 2, "a": 1}) == cache_service.hash({"a": 1, "b": 2})


# ---------------------------------------------------------------------------
# list_namespaces / list_values / get_stats
# ---------------------------------------------------------------------------


class TestListAndStats:
    def test_list_namespaces_includes_populated_namespaces(self, cache_service: DiskCacheService) -> None:
        cache_service.set("k", "v", namespace="alpha")
        cache_service.set("k", "v", namespace="beta")
        namespaces = cache_service.list_namespaces()
        assert "alpha" in namespaces
        assert "beta" in namespaces

    def test_list_values_returns_stored_values(self, cache_service: DiskCacheService) -> None:
        cache_service.set("k1", "val-a", namespace="ns")
        cache_service.set("k2", "val-b", namespace="ns")
        values = list(cache_service.list_values(namespace="ns"))
        assert "val-a" in values
        assert "val-b" in values

    def test_list_values_excludes_ttl_metadata_entries(self, cache_service: DiskCacheService) -> None:
        cache_service.set("k", "v", namespace="ns", ttl=3600)
        values = list(cache_service.list_values(namespace="ns"))
        assert all(not isinstance(v, str) or not v.startswith("16") for v in values)
        assert "v" in values

    def test_list_values_respects_limit(self, cache_service: DiskCacheService) -> None:
        for i in range(5):
            cache_service.set(f"k{i}", f"v{i}", namespace="ns")
        values = list(cache_service.list_values(namespace="ns", limit=2))
        assert len(values) == 2

    def test_get_stats_has_expected_fields(self, cache_service: DiskCacheService) -> None:
        stats = cache_service.get_stats()
        assert "cache_dir" in stats
        assert "size" in stats
        assert "size_limit" in stats
        assert "eviction_policy" in stats


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_is_noop(self, cache_service: DiskCacheService) -> None:
        await cache_service.on_startup()

    async def test_on_shutdown_calls_close(self, cache_service: DiskCacheService) -> None:
        with patch.object(cache_service, "close") as mock_close:
            await cache_service.on_shutdown()
        mock_close.assert_called_once()

    def test_context_manager_returns_self(self, tmp_path, mock_registry, mock_config) -> None:
        with DiskCacheService(cache_dir=str(tmp_path / "ctx-cache")) as svc:
            assert isinstance(svc, DiskCacheService)
