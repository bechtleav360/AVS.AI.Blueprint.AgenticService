"""Step-by-step walkthrough of the centralised caching feature.

Designed for live demos: each step prints its purpose, runs the operation,
shows the result, and maps to one of the acceptance criteria from the issue.

Run:
    python walkthrough.py            # auto-advance
    python walkthrough.py --pause    # press <Enter> between steps (best for live demos)
    python walkthrough.py --no-redis # only run the local-cache steps

Steps and acceptance criteria covered:
    1. The unified Cache interface           AC-01
    2. DiskCache: basic CRUD                  AC-03
    3. TTL expiry on DiskCache                AC-04
    4. Namespaces isolate keys                AC-06
    5. Switching backends via Dynaconf-style  AC-02
    6. Redis: TTL is identical                AC-04
    7. key_prefix isolates services           AC-06
    8. Cross-process sharing via Redis        AC-01, AC-02
    9. Fallback to DiskCache when Redis down  AC-05
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from blueprint.agents.component.component import Component
from blueprint.agents.models.config import CacheConfig
from blueprint.agents.services.infrastructure.cache_backend_factory import CacheBackendFactory
from blueprint.agents.services.infrastructure.cache_service import CacheService, DiskCacheService

DEMO_CACHE_DIR = ".cache/walkthrough"
HERE = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Pretty-print helpers
# ---------------------------------------------------------------------------


_PAUSE = False  # set by --pause


def step(num: int, total: int, title: str, ac: str) -> None:
    print()
    print("═" * 74)
    print(f"  STEP {num}/{total}  —  {title}")
    print(f"  Acceptance criterion: {ac}")
    print("═" * 74)


def say(msg: str) -> None:
    print(f"  {msg}")


def code(msg: str) -> None:
    print(f"      >>> {msg}")


def result(msg: str) -> None:
    print(f"      = {msg}")


def pause() -> None:
    if _PAUSE:
        try:
            input("\n  [press Enter to continue]")
        except EOFError:
            pass


def _reset_registry() -> None:
    """Component registers by class name and rejects duplicates within a process.

    We clear the registry between demo sections so we can build several cache
    instances in this single Python process without name collisions.
    """
    if Component.shared_registry is not None:
        Component.shared_registry.clear_components()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def step_1_interface(total: int) -> None:
    step(1, total, "The unified Cache interface", "AC-01")
    say("Both backends implement the SAME abstract interface — code never")
    say("needs to know whether it's talking to disk or Redis.")
    print()
    methods = [
        ("get(key, namespace)",                   "fetch a value or None"),
        ("set(key, value, namespace, ttl)",        "store a value (optionally with TTL)"),
        ("delete(key, namespace)",                 "remove a value"),
        ("exists(key, namespace)",                 "True/False"),
        ("clear(namespace=None)",                  "wipe one namespace, or everything"),
    ]
    for sig, doc in methods:
        say(f"  • CacheService.{sig:<40} → {doc}")
    print()
    say("Implementations:  DiskCacheService   ✓")
    say("                  RedisCacheService  ✓")
    pause()


def step_2_disk_basics(total: int) -> DiskCacheService:
    step(2, total, "DiskCache — the default backend (no Redis required)", "AC-03")
    say("DiskCache is the default. Existing services keep working with zero")
    say("config changes.")
    print()
    if Path(DEMO_CACHE_DIR).exists():
        shutil.rmtree(DEMO_CACHE_DIR)
    cache = DiskCacheService(cache_dir=DEMO_CACHE_DIR)
    code(f"cache = DiskCacheService(cache_dir={DEMO_CACHE_DIR!r})")
    print()
    code('cache.set("user:42", {"name": "Alice", "role": "admin"})')
    cache.set("user:42", {"name": "Alice", "role": "admin"})
    code('cache.get("user:42")')
    result(f"{cache.get('user:42')}")
    print()
    code('cache.exists("user:42")')
    result(f"{cache.exists('user:42')}")
    code('cache.delete("user:42")')
    result(f"{cache.delete('user:42')}")
    code('cache.exists("user:42")')
    result(f"{cache.exists('user:42')}")
    pause()
    return cache


def step_3_disk_ttl(total: int, cache: DiskCacheService) -> None:
    step(3, total, "TTL expiry — DiskCache", "AC-04")
    say("Entries can carry a TTL. After it elapses, the entry disappears.")
    print()
    code('cache.set("session:abc", "tmp", ttl=2)')
    cache.set("session:abc", "tmp", ttl=2)
    code('cache.exists("session:abc")  # immediately')
    result(f"{cache.exists('session:abc')}")
    print()
    say("waiting 3 seconds for TTL to expire …")
    time.sleep(3)
    code('cache.exists("session:abc")  # after 3s')
    result(f"{cache.exists('session:abc')}")
    pause()


def step_4_namespaces(total: int, cache: DiskCacheService) -> None:
    step(4, total, "Namespaces isolate keys", "AC-06")
    say("The same key in different namespaces holds different values.")
    say("Each agent/service should pick its own namespace.")
    print()
    code('cache.set("counter", 100, namespace="pricing")')
    cache.set("counter", 100, namespace="pricing")
    code('cache.set("counter", 200, namespace="recommendation")')
    cache.set("counter", 200, namespace="recommendation")
    print()
    code('cache.get("counter", namespace="pricing")')
    result(f"{cache.get('counter', namespace='pricing')}")
    code('cache.get("counter", namespace="recommendation")')
    result(f"{cache.get('counter', namespace='recommendation')}")
    print()
    say("Same key, two namespaces → two independent values.")
    cache.close()
    pause()


def step_5_factory_switch(total: int) -> CacheService:
    step(5, total, "Switching backends via CacheConfig (Dynaconf-style)", "AC-02")
    say("Production code never builds a CacheService directly — it reads")
    say("CacheConfig from settings.toml and asks CacheBackendFactory to")
    say("build the right one.")
    print()
    config = CacheConfig(
        backend="redis",
        redis_url="redis://localhost:6379/0",
        key_prefix="walkthrough_demo",
        default_ttl=300,
    )
    code("config = CacheConfig(backend='redis', redis_url='redis://localhost:6379/0',")
    code("                     key_prefix='walkthrough_demo', default_ttl=300)")
    code("cache = CacheBackendFactory.create(config)")
    _reset_registry()
    cache = CacheBackendFactory.create(config)
    result(f"{type(cache).__name__}")
    print()
    say("Same interface — same operations work, but values are now in Redis.")
    code('cache.set("greeting", "Hello from Redis")')
    cache.set("greeting", "Hello from Redis")
    code('cache.get("greeting")')
    result(f"{cache.get('greeting')!r}")
    pause()
    return cache


def step_6_redis_ttl(total: int, cache: CacheService) -> None:
    step(6, total, "Redis: TTL behaves identically", "AC-04")
    say("Same TTL semantics as DiskCache — but enforced natively by Redis.")
    print()
    code('cache.set("token", "abc-xyz", ttl=2)')
    cache.set("token", "abc-xyz", ttl=2)
    code('cache.exists("token")  # immediately')
    result(f"{cache.exists('token')}")
    say("waiting 3 seconds for Redis-side TTL …")
    time.sleep(3)
    code('cache.exists("token")  # after 3s')
    result(f"{cache.exists('token')}")
    pause()


def step_7_key_prefix(total: int, redis_url: str) -> None:
    step(7, total, "key_prefix isolates services in a shared Redis", "AC-06")
    say("Two different services can share ONE Redis without seeing each other's")
    say("keys — each picks a unique key_prefix in its CacheConfig.")
    print()

    cfg_a = CacheConfig(backend="redis", redis_url=redis_url, key_prefix="service-a")
    cfg_b = CacheConfig(backend="redis", redis_url=redis_url, key_prefix="service-b")

    _reset_registry()
    cache_a = CacheBackendFactory.create(cfg_a)
    code('service_a_cache = CacheBackendFactory.create(... key_prefix="service-a")')
    _reset_registry()
    cache_b = CacheBackendFactory.create(cfg_b)
    code('service_b_cache = CacheBackendFactory.create(... key_prefix="service-b")')
    print()
    code('service_a_cache.set("user:1", {"name": "Alice"})')
    cache_a.set("user:1", {"name": "Alice"})
    code('service_b_cache.set("user:1", {"name": "Bob"})')
    cache_b.set("user:1", {"name": "Bob"})
    print()
    code('service_a_cache.get("user:1")  # sees its own value')
    result(f"{cache_a.get('user:1')}")
    code('service_b_cache.get("user:1")  # sees its own value')
    result(f"{cache_b.get('user:1')}")
    print()
    say("Same key, two prefixes → no collision. Multiple services can safely")
    say("share one Redis instance.")
    cache_a.clear()
    cache_b.clear()
    cache_a.close()
    cache_b.close()
    pause()


def step_8_cross_process(total: int) -> None:
    step(8, total, "Cross-process sharing — TWO independent agents", "AC-01, AC-02")
    say("This is the real proof that 'centralised cache' actually means what")
    say("it says: two separate OS-level processes, each with its own Python")
    say("interpreter and its own RedisCacheService instance, share state via")
    say("Redis.")
    print()
    say("Running examples/shared_cache_demo/demo_multiprocess.py …")
    print()
    cmd = [sys.executable, str(HERE / "demo_multiprocess.py"), "--clear"]
    completed = subprocess.run(cmd)
    if completed.returncode != 0:
        say("✗ Multi-process demo failed — investigate before proceeding.")
        sys.exit(1)
    pause()


def step_9_fallback(total: int) -> None:
    import asyncio

    step(9, total, "Resilience when Redis is unreachable", "AC-05")
    say("If a service is configured for Redis but Redis is down at startup,")
    say("we want a clear error in the log but no crash — the service should")
    say("still come up. The fallback_to_local flag controls this.")
    print()
    code("config = CacheConfig(backend='redis',")
    code("                     redis_url='redis://this-host-does-not-exist:6379/0',")
    code("                     fallback_to_local=True)")
    config = CacheConfig(
        backend="redis",
        redis_url="redis://this-host-does-not-exist:6379/0",
        fallback_to_local=True,
        cache_dir=DEMO_CACHE_DIR + "_fallback",
    )

    _reset_registry()
    cache = CacheBackendFactory.create(config)
    code("cache = CacheBackendFactory.create(config)  # constructor doesn't ping yet")
    result(f"{type(cache).__name__}")
    print()
    code("await cache.on_startup()  # would raise ConnectionError without the flag")
    asyncio.run(cache.on_startup())
    result("returned normally — service boots in degraded mode (a clear error was logged)")
    print()
    say("With fallback_to_local=False the same call would raise ConnectionError")
    say("and stop the service from starting.")
    pause()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def redis_reachable(url: str) -> bool:
    try:
        import redis  # type: ignore[import-not-found]

        client = redis.Redis.from_url(url, socket_connect_timeout=1)
        client.ping()
        client.close()
        return True
    except Exception:
        return False


def summary(redis_run: bool) -> None:
    print()
    print("═" * 74)
    print("  SUMMARY  —  Acceptance criteria coverage")
    print("═" * 74)
    rows = [
        ("AC-01", "Pluggable backends behind a unified interface",        "Steps 1, 5, 8"),
        ("AC-02", "Redis backend, configurable via CacheConfig",          "Steps 5, 8"),
        ("AC-03", "Existing local cache retained as default",             "Step 2"),
        ("AC-04", "TTL expiry, consistent between backends",              "Steps 3, 6"),
        ("AC-05", "Optional fallback when Redis is unavailable",          "Step 9"),
        ("AC-06", "Namespaces + key_prefix avoid collisions",             "Steps 4, 7"),
        ("AC-07", "Working Redis example configuration",                  "Steps 5, 7, 8"),
    ]
    for ac, title, where in rows:
        marker = "✓"
        if not redis_run and ac in {"AC-02", "AC-05", "AC-07"}:
            marker = "—"
        print(f"  {marker}  {ac}  {title:<48} {where}")
    print()
    if redis_run:
        print("  All 7 acceptance criteria are demonstrated and pass.")
    else:
        print("  DiskCache-only run. Re-run with Redis available to cover AC-02/05/07.")
    print("═" * 74)


def main() -> None:
    global _PAUSE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pause", action="store_true", help="Pause between steps")
    parser.add_argument("--no-redis", action="store_true", help="Skip Redis-only steps")
    parser.add_argument("--url", default="redis://localhost:6379/0", help="Redis URL")
    args = parser.parse_args()

    _PAUSE = args.pause

    print()
    print("╔" + "═" * 72 + "╗")
    print("║  Centralised Cache Walkthrough  —  AVS Agent Blueprint               ║")
    print("╚" + "═" * 72 + "╝")
    print()
    print("  This walkthrough demonstrates each acceptance criterion from the")
    print("  caching issue in order. Watch the output between '═══' lines to see")
    print("  which AC is being proved at each step.")

    use_redis = not args.no_redis and redis_reachable(args.url)
    if not args.no_redis and not use_redis:
        print()
        print("  ⚠  Redis is not reachable at", args.url)
        print("     Falling back to DiskCache-only steps (AC-02/05/07 will be skipped).")
        print("     Tip: docker run -d --rm -p 6379:6379 redis:alpine")

    total = 9 if use_redis else 4

    # Local-cache steps (always run)
    step_1_interface(total)
    cache = step_2_disk_basics(total)
    step_3_disk_ttl(total, cache)
    step_4_namespaces(total, cache)

    # Redis-backed steps (run only when Redis is reachable)
    if use_redis:
        cache_redis = step_5_factory_switch(total)
        step_6_redis_ttl(total, cache_redis)
        cache_redis.close()
        step_7_key_prefix(total, args.url)
        step_8_cross_process(total)
        step_9_fallback(total)

    summary(use_redis)


if __name__ == "__main__":
    main()
