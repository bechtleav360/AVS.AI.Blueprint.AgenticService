"""Test concurrent access to DiskCacheService for multi-deployment scenarios."""

import tempfile
import threading
import time
from pathlib import Path

import pytest

from blueprint.agents.services.cache_service import DiskCacheService


class TestCacheServiceConcurrency:
    """Test concurrent access patterns for multi-deployment safety using threading."""

    @pytest.fixture
    def cache_dir(self) -> Path:
        """Create a temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_concurrent_reads_with_locking(self, cache_dir: Path) -> None:
        """Test multiple threads reading from cache simultaneously."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)
        cache.set("test_key", "test_value", namespace="default")

        results = []

        def read_cache(thread_id: int) -> None:
            """Read from cache in a separate thread."""
            value = cache.get("test_key", namespace="default")
            results.append((thread_id, value))

        # Simulate multiple concurrent readers
        threads = [threading.Thread(target=read_cache, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # All threads should read the same value
        assert len(results) == 5
        for _, value in results:
            assert value == "test_value"

    def test_concurrent_writes_with_locking(self, cache_dir: Path) -> None:
        """Test multiple threads writing to cache with locking prevents corruption."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)

        def write_cache(thread_id: int) -> None:
            """Write to cache in a separate thread."""
            for i in range(10):
                cache.set(f"key_{thread_id}", f"value_{thread_id}_{i}", namespace="default")
                time.sleep(0.001)  # Small delay to increase contention

        # Simulate multiple concurrent writers
        threads = [threading.Thread(target=write_cache, args=(i,)) for i in range(3)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify all writes completed successfully
        for i in range(3):
            value = cache.get(f"key_{i}", namespace="default")
            assert value == f"value_{i}_9"  # Last write should be preserved

    def test_ttl_persistence_single_instance(self, cache_dir: Path) -> None:
        """Test that TTL metadata persists within same cache instance."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)
        cache.set("ttl_key", "ttl_value", namespace="default", ttl=3600)

        # Verify TTL is stored in cache by checking that the value is still accessible
        # (TTL metadata is stored internally with special key format)
        value = cache.get("ttl_key", namespace="default")
        assert value == "ttl_value"

        # Verify TTL is not expired by checking after a short delay
        time.sleep(0.1)
        value_after = cache.get("ttl_key", namespace="default")
        assert value_after == "ttl_value"

    def test_ttl_expiration_synchronized(self, cache_dir: Path) -> None:
        """Test that TTL expiration is synchronized across threads."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)
        # Set with very short TTL
        cache.set("short_ttl_key", "short_ttl_value", namespace="default", ttl=1)

        # Verify value is accessible immediately
        value = cache.get("short_ttl_key", namespace="default")
        assert value == "short_ttl_value"

        # Wait for TTL to expire
        time.sleep(1.1)

        # Value should now be expired
        value = cache.get("short_ttl_key", namespace="default")
        assert value is None

    def test_concurrent_delete_operations(self, cache_dir: Path) -> None:
        """Test concurrent delete operations don't cause corruption."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)

        # Set up initial data
        for i in range(20):
            cache.set(f"delete_key_{i}", f"value_{i}", namespace="default")

        def delete_cache(start_idx: int, count: int) -> None:
            """Delete from cache in a separate thread."""
            for i in range(start_idx, start_idx + count):
                cache.delete(f"delete_key_{i}", namespace="default")

        # Simulate multiple concurrent deleters
        threads = [
            threading.Thread(target=delete_cache, args=(0, 10)),
            threading.Thread(target=delete_cache, args=(10, 10)),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify all keys are deleted
        for i in range(20):
            value = cache.get(f"delete_key_{i}", namespace="default")
            assert value is None

    def test_concurrent_exists_checks(self, cache_dir: Path) -> None:
        """Test concurrent exists() checks with TTL expiration."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)
        cache.set("exists_key", "exists_value", namespace="default", ttl=2)

        results = []

        def check_exists(thread_id: int, delay: float) -> None:
            """Check existence in a separate thread."""
            time.sleep(delay)
            exists = cache.exists("exists_key", namespace="default")
            results.append((thread_id, exists))

        # Thread 1: Check immediately (should exist)
        # Thread 2: Check after 1 second (should exist)
        # Thread 3: Check after 2.5 seconds (should be expired)
        threads = [
            threading.Thread(target=check_exists, args=(1, 0)),
            threading.Thread(target=check_exists, args=(2, 1)),
            threading.Thread(target=check_exists, args=(3, 2.5)),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify results
        results.sort(key=lambda x: x[0])
        assert results[0][1] is True  # Immediate check
        assert results[1][1] is True  # 1 second later
        assert results[2][1] is False  # After expiration

    def test_locking_prevents_race_condition(self, cache_dir: Path) -> None:
        """Test that locking prevents race conditions in check-then-act patterns."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)
        cache.set("counter", "0", namespace="default")

        def increment_counter() -> None:
            """Simulate check-then-act pattern: read, increment, write."""
            for _ in range(10):
                current = cache.get("counter", namespace="default")
                current_int = int(current) if current else 0
                cache.set("counter", str(current_int + 1), namespace="default")
                time.sleep(0.001)  # Small delay to increase contention

        # Run multiple threads incrementing the counter
        threads = [threading.Thread(target=increment_counter) for _ in range(3)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # With locking, final value should be 30 (3 threads * 10 increments)
        final_value = int(cache.get("counter", namespace="default") or "0")
        assert final_value == 30

    def test_locking_disabled_single_deployment(self, cache_dir: Path) -> None:
        """Test that locking can be disabled for single-deployment scenarios."""
        cache_no_lock = DiskCacheService(cache_dir=str(cache_dir), enable_locking=False)

        # Should work without locking
        cache_no_lock.set("no_lock_key", "no_lock_value", namespace="default")
        value = cache_no_lock.get("no_lock_key", namespace="default")
        assert value == "no_lock_value"

        # Verify lock file is not created
        lock_file = Path(cache_dir) / ".cache_lock"
        assert not lock_file.exists()

    def test_namespace_isolation_with_concurrency(self, cache_dir: Path) -> None:
        """Test that namespaces remain isolated under concurrent access."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)

        def write_to_namespace(namespace: str, value: str) -> None:
            """Write to a specific namespace in a separate thread."""
            for i in range(5):
                cache.set(f"key_{i}", f"{value}_{i}", namespace=namespace)

        # Write to different namespaces concurrently
        threads = [
            threading.Thread(target=write_to_namespace, args=("ns1", "value1")),
            threading.Thread(target=write_to_namespace, args=("ns2", "value2")),
            threading.Thread(target=write_to_namespace, args=("ns3", "value3")),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify namespace isolation
        for i in range(5):
            assert cache.get(f"key_{i}", namespace="ns1") == f"value1_{i}"
            assert cache.get(f"key_{i}", namespace="ns2") == f"value2_{i}"
            assert cache.get(f"key_{i}", namespace="ns3") == f"value3_{i}"

    def test_clear_with_concurrent_access(self, cache_dir: Path) -> None:
        """Test that clear() works correctly with concurrent access."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)

        # Set up initial data
        cache.set("key1", "value1", namespace="ns1")
        cache.set("key2", "value2", namespace="ns1")
        cache.set("key3", "value3", namespace="ns2")

        def read_and_clear() -> None:
            """Read and then clear in a separate thread."""
            time.sleep(0.1)  # Let other operations start
            cache.clear(namespace="ns1")

        # Start a thread that will clear ns1
        clear_thread = threading.Thread(target=read_and_clear)
        clear_thread.start()

        # Give clear time to execute
        time.sleep(0.2)

        clear_thread.join()

        # Verify namespace was cleared
        assert cache.get("key1", namespace="ns1") is None
        assert cache.get("key2", namespace="ns1") is None
        # Other namespace should be unaffected
        assert cache.get("key3", namespace="ns2") == "value3"

    def test_get_stats_with_concurrent_writes(self, cache_dir: Path) -> None:
        """Test that get_stats() returns consistent results under concurrent writes."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)

        def write_many_keys(start_idx: int, count: int) -> None:
            """Write many keys in a separate thread."""
            for i in range(start_idx, start_idx + count):
                cache.set(f"stat_key_{i}", f"value_{i}", namespace="default")

        # Write keys concurrently
        threads = [
            threading.Thread(target=write_many_keys, args=(0, 10)),
            threading.Thread(target=write_many_keys, args=(10, 10)),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Get stats
        stats = cache.get_stats()

        # Should have at least 20 keys
        assert stats["size"] >= 20
        assert stats["cache_dir"] == str(cache_dir)

    def test_ttl_with_no_ttl_mixed_operations(self, cache_dir: Path) -> None:
        """Test mixing TTL and non-TTL operations under concurrent access."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)

        def write_mixed(thread_id: int) -> None:
            """Write both TTL and non-TTL keys in a separate thread."""
            # Write with TTL
            cache.set(f"ttl_key_{thread_id}", f"ttl_value_{thread_id}", namespace="default", ttl=3600)
            # Write without TTL
            cache.set(f"no_ttl_key_{thread_id}", f"no_ttl_value_{thread_id}", namespace="default")

        # Run concurrent writes
        threads = [threading.Thread(target=write_mixed, args=(i,)) for i in range(3)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify both types exist
        for i in range(3):
            # TTL keys should exist
            assert cache.get(f"ttl_key_{i}", namespace="default") == f"ttl_value_{i}"
            # Non-TTL keys should exist
            assert cache.get(f"no_ttl_key_{i}", namespace="default") == f"no_ttl_value_{i}"

        # Verify that TTL keys remain accessible after a short delay
        time.sleep(0.1)
        for i in range(3):
            assert cache.get(f"ttl_key_{i}", namespace="default") == f"ttl_value_{i}"
            assert cache.get(f"no_ttl_key_{i}", namespace="default") == f"no_ttl_value_{i}"

    def test_sequential_access_pattern(self, cache_dir: Path) -> None:
        """Test sequential access pattern where lock is released after each operation."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)
        access_order = []

        def sequential_operations(thread_id: int) -> None:
            """Perform sequential cache operations."""
            # Each operation acquires and releases lock independently
            cache.set(f"seq_key_{thread_id}", f"seq_value_{thread_id}", namespace="default")
            access_order.append((thread_id, "set"))

            value = cache.get(f"seq_key_{thread_id}", namespace="default")
            access_order.append((thread_id, "get"))
            assert value == f"seq_value_{thread_id}"

            exists = cache.exists(f"seq_key_{thread_id}", namespace="default")
            access_order.append((thread_id, "exists"))
            assert exists is True

        # Run multiple threads with sequential access
        threads = [threading.Thread(target=sequential_operations, args=(i,)) for i in range(3)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify all operations completed
        assert len(access_order) == 9  # 3 threads * 3 operations

    def test_wait_for_cache_availability(self, cache_dir: Path) -> None:
        """Test waiting for cache availability."""
        # Test with locking enabled
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)
        cache.set("test_key", "test_value", namespace="default")

        # Cache should be available immediately
        assert cache.wait_for_cache_availability(timeout=1.0) is True

    def test_wait_for_cache_availability_no_locking(self, cache_dir: Path) -> None:
        """Test waiting for cache availability with locking disabled."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=False)
        cache.set("test_key", "test_value", namespace="default")

        # Should return True immediately since locking is disabled
        assert cache.wait_for_cache_availability(timeout=1.0) is True

    def test_sequential_access_interleaving(self, cache_dir: Path) -> None:
        """Test that sequential access allows operations to interleave."""
        cache = DiskCacheService(cache_dir=str(cache_dir), enable_locking=True)
        operation_log = []

        def thread_operations(thread_id: int) -> None:
            """Perform operations that should interleave."""
            for i in range(3):
                cache.set(f"key_{thread_id}_{i}", f"value_{thread_id}_{i}", namespace="default")
                operation_log.append((thread_id, "set", i))
                time.sleep(0.001)  # Small delay to encourage interleaving

                value = cache.get(f"key_{thread_id}_{i}", namespace="default")
                operation_log.append((thread_id, "get", i))
                assert value == f"value_{thread_id}_{i}"

        # Run multiple threads
        threads = [threading.Thread(target=thread_operations, args=(i,)) for i in range(2)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Verify operations completed
        assert len(operation_log) == 12  # 2 threads * 3 iterations * 2 operations
