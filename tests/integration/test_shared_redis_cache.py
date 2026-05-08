"""Integration tests: cross-instance Redis cache sharing.

These tests require a real Redis server. They are skipped automatically
when Redis is not reachable, so CI does not need a Redis sidecar unless
you explicitly want to run them.

Run with a local Redis:
    docker run -d -p 6379:6379 redis:alpine
    pytest tests/integration/test_shared_redis_cache.py -v
"""

import subprocess
import sys
import textwrap

import pytest
import redis

REDIS_URL = "redis://localhost:6379/0"
KEY_PREFIX = "pytest_shared_cache"


# ---------------------------------------------------------------------------
# Fixture: skip the whole module when Redis is unavailable
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def redis_url() -> str:
    try:
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        client.close()
    except Exception:
        pytest.skip("Redis is not available at localhost:6379 — skipping integration tests")
    return REDIS_URL


@pytest.fixture(autouse=True)
def _reset_component_registry():
    """Clear the shared Component registry between tests.

    Component.__init__ registers each instance under its class-derived snake-case
    name and rejects duplicates. Without resetting, the second cache constructed
    in this module fails with 'Component with name redis_cache_service already exists'.
    The registry is lazily created on first construction, so it may be None initially.
    """
    from blueprint.agents.component.component import Component

    def _clear() -> None:
        if Component.shared_registry is not None:
            Component.shared_registry.clear_components()

    _clear()
    yield
    _clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_reader(redis_url: str, key: str, namespace: str, key_prefix: str) -> dict | None:
    """Spawn a subprocess that creates its own RedisCacheService and reads one key.

    Returns the cached value (dict) if the key is found, otherwise None.
    """
    script = textwrap.dedent(f"""
        import json, sys
        from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService
        cache = RedisCacheService(redis_url={redis_url!r}, key_prefix={key_prefix!r})
        value = cache.get({key!r}, namespace={namespace!r})
        cache.close()
        if value is None:
            sys.exit(1)
        print(json.dumps(value))
    """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    try:
        import json
        return json.loads(result.stdout.strip())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_two_processes_share_cache(redis_url: str) -> None:
    """A value written in this process can be read by an independent subprocess."""
    from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService

    namespace = "cross_process"
    key = "shared_value"
    expected = {"hello": "from-writer", "number": 42}

    writer = RedisCacheService(redis_url=redis_url, key_prefix=KEY_PREFIX)
    try:
        writer.set(key, expected, namespace=namespace)
    finally:
        writer.close()

    value = _run_reader(redis_url, key, namespace, KEY_PREFIX)
    assert value == expected, f"Subprocess read {value!r}, expected {expected!r}"


@pytest.mark.integration
def test_namespace_isolation_across_instances(redis_url: str) -> None:
    """Two instances with different key_prefix values cannot see each other's keys."""
    from blueprint.agents.component.component import Component
    from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService

    namespace = "isolation"
    key = "secret"

    instance_a = RedisCacheService(redis_url=redis_url, key_prefix=f"{KEY_PREFIX}_instance_a")
    # Component registers by class name; clear so a 2nd instance can be built in this process
    if Component.shared_registry is not None:
        Component.shared_registry.clear_components()
    instance_b = RedisCacheService(redis_url=redis_url, key_prefix=f"{KEY_PREFIX}_instance_b")

    try:
        instance_a.set(key, {"owner": "a"}, namespace=namespace)

        assert instance_a.get(key, namespace=namespace) == {"owner": "a"}
        assert instance_b.get(key, namespace=namespace) is None, (
            "Instance B should not see Instance A's key (different key_prefix)"
        )
    finally:
        instance_a.clear()
        instance_b.clear()
        instance_a.close()
        instance_b.close()


@pytest.mark.integration
def test_ttl_expiry_is_enforced(redis_url: str) -> None:
    """An entry set with TTL=1 must not be visible after 2 seconds."""
    import time

    from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService

    namespace = "ttl_check"
    key = "expiring_key"

    cache = RedisCacheService(redis_url=redis_url, key_prefix=KEY_PREFIX)
    try:
        cache.set(key, {"data": "temporary"}, namespace=namespace, ttl=1)
        assert cache.exists(key, namespace=namespace), "Entry should exist immediately after set()"

        time.sleep(2)

        assert not cache.exists(key, namespace=namespace), (
            "Entry should have expired after TTL elapsed"
        )
    finally:
        cache.close()
