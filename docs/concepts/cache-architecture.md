# Cache Architecture

This document describes the **pluggable cache architecture** introduced for centralised caching support. It explains the components, their responsibilities, and the design choices behind them.

For end-user setup instructions, see [Caching — Getting Started](../guides/caching-getting-started.md). For a higher-level system overview with diagrams, see [Cache System Overview](./cache-system-overview.md).

---

## Goals

The architecture solves three problems:

| Problem | Solution |
|---|---|
| Scaling out causes cache misses on every replica | Shared backend (Redis) so all replicas see the same cache |
| Different deployments need different storage backends | Pluggable backend behind a single interface |
| Existing single-replica services should not be forced to change | Local DiskCache stays the default |

## Components

```
                  ┌─────────────────────────────────────┐
                  │  CacheService  (abstract interface) │
                  │                                     │
                  │   get / set / delete / exists       │
                  │   clear / hash / get_stats          │
                  └─────────────────────────────────────┘
                              ▲                ▲
                              │                │
              ┌───────────────┘                └───────────────┐
              │                                                │
   ┌──────────────────────┐                       ┌──────────────────────┐
   │  DiskCacheService    │                       │  RedisCacheService   │
   │  (default, local)    │                       │  (centralised)       │
   │                      │                       │                      │
   │  diskcache-rs        │                       │  redis-py 7.x        │
   │  per-process file    │                       │  shared TCP client   │
   └──────────────────────┘                       └──────────────────────┘

                              ▲
                              │   creates the right one based on
                              │   CacheConfig.backend
                              │
                  ┌─────────────────────────────────────┐
                  │  CacheBackendFactory                │
                  │   .create(CacheConfig) → CacheService│
                  └─────────────────────────────────────┘
                              ▲
                              │   reads from settings.toml
                              │
                  ┌─────────────────────────────────────┐
                  │  Config.get_cache_config()           │
                  │   returns a CacheConfig (Pydantic)   │
                  └─────────────────────────────────────┘
                              ▲
                              │   wires the cache into the registry
                              │
                  ┌─────────────────────────────────────┐
                  │  AppBuilder.with_cache()             │
                  │   → Component.shared_registry        │
                  │     .cache_service = …               │
                  └─────────────────────────────────────┘
                              ▲
                              │   pulled by every service / handler
                              │   in their on_startup()
                              │
              ┌───────────────┴────────────────┐
              │                                │
        ┌──────────┐                     ┌──────────┐
        │ ServiceA │                     │ ServiceB │
        │          │                     │          │
        │ self.    │                     │ self.    │
        │ registry │                     │ registry │
        │ .cache_  │                     │ .cache_  │
        │ service  │                     │ service  │
        └──────────┘                     └──────────┘
```

### `CacheService` — the abstract interface
`src/blueprint/agents/services/infrastructure/cache_service.py`

Five operations every backend must implement: `get`, `set`, `delete`, `exists`, `clear`. Plus `hash` for normalised key generation, `get_stats` for the management API, and `list_namespaces` / `list_values` for the cache REST endpoints.

Code that uses the cache only sees this interface — it never imports `DiskCacheService` or `RedisCacheService` directly.

### `DiskCacheService` — local default
Same file. Backed by `diskcache-rs` (a Rust-accelerated diskcache port). Persists to a directory on disk. Thread-safe via an optional `RLock`. **Default** — services that don't change anything continue to work exactly as before.

### `RedisCacheService` — centralised, shared
`src/blueprint/agents/services/infrastructure/redis_cache_service.py`

Backed by `redis-py 7.x`. Uses Redis-native TTL via the `EX` argument on `SET`. Namespace + key are joined with `:` and prefixed by an optional `key_prefix` so multiple services can share one Redis instance without collisions.

### `CacheBackendFactory` — Strategy selector
`src/blueprint/agents/services/infrastructure/cache_backend_factory.py`

A simple `@staticmethod` that returns a `DiskCacheService` or a `RedisCacheService` depending on `CacheConfig.backend`. This is where the **Strategy pattern** lives — it picks the concrete strategy at runtime based on configuration.

### `CacheConfig` — typed configuration
`src/blueprint/agents/models/config.py`

Pydantic model. Holds: `backend`, `cache_dir`, `default_ttl`, `key_prefix`, `redis_url`, `redis_password`, `redis_db`, `redis_tls`, `fallback_to_local`. Read from `settings.toml` via Dynaconf in `Config.get_cache_config()`.

### `AppBuilder.with_cache()` — wiring
`src/blueprint/agents/app_builder.py`

```python
def with_cache(self, enabled: bool = True, enable_locking: bool = True) -> "AppBuilder":
    if enabled:
        cache_config = self._config.get_cache_config()
        cache_service = CacheBackendFactory.create(cache_config, enable_locking=enable_locking)
        Component.shared_registry.cache_service = cache_service
    return self
```

Calling `with_cache()` is the **only** thing a service author needs to do to opt in. The factory picks the backend, the registry stores the singleton, and every component can pull it from `self.registry.cache_service`.

---

## Design choices

### Why a Strategy pattern, not subclassing the cache?

Because the **calling code** (services, handlers, agents) does not know — and should not know — which backend is in use. With Strategy:

- Services depend only on `CacheService` (the interface).
- Choosing backend is a one-line change in `settings.toml`.
- New backends (Memcached, DynamoDB, …) can be added by implementing `CacheService` without touching any caller.

### Why keep DiskCache as default?

Two reasons:
1. **No breaking changes** — every existing service that already used the cache keeps working.
2. **Zero-dependency baseline** — single-replica deployments don't need Redis just to use the cache.

### Why a single global registry instead of injecting the cache per service?

Because `Component.shared_registry` is the existing mechanism for cross-component dependency lookup (services look up other services there too). Reusing it keeps the API uniform and the singleton guarantee enforced by the registry's "set once" check.

### Why `key_prefix` AND `namespace`?

Two layers of isolation, two scopes:
- **`namespace`** is *per-call* (`cache.get(k, namespace="prices")`) — used by code to organise its own keys.
- **`key_prefix`** is *per-instance* (configured once in `settings.toml`) — used to keep multiple services that share one Redis instance from colliding.

A Redis key looks like `{key_prefix}:{namespace}:{hash(key)}`.

### Why a sync redis-py client in async services?

Redis operations are normally sub-millisecond and the cache is on the hot path. The sync client is simpler, well-tested, and the latency cost is negligible for typical agent workloads. If that ever becomes a bottleneck, an `AsyncRedisCacheService` can be added without changing any caller.

### What about fallback when Redis is unreachable?

Two failure modes are distinguished:
1. **`redis` package not installed** — `CacheBackendFactory` falls back to `DiskCacheService` if `fallback_to_local=True`. This is a **real backend swap** — the app runs with disk thereafter.
2. **Redis unreachable at startup or runtime** — `RedisCacheService` keeps trying Redis. With `fallback_to_local=True`, `on_startup()` does not raise; with `fallback_to_local=False`, it raises and the pod crashes (K8s restarts it).

In case (2) the cache is not silently swapped to disk. Operations against an unreachable Redis return `None`/`False` and log warnings.

To prevent a pod from silently serving cache misses while looking healthy to K8s, the framework registers a `CacheHealthChecker` for the readiness probe automatically when `with_cache()` is called:

- `/health/ready` → returns **HTTP 503** with full diagnostic payload when Redis is unreachable
- `/health/live` → unaffected (always 200) — the pod stays alive
- Recovery is automatic — when Redis returns, the next health-check tick (≤ `health_check_interval_seconds`, default 30s) flips readiness back to UP and K8s re-adds the pod to the service pool

For DiskCache, the health check is trivially UP (the local filesystem doesn't fail in the same way a network service does).

---

## What's now possible with this architecture

| Before | After |
|---|---|
| Each replica had its own DiskCache → cache misses after every restart and on every new replica | Replicas share a single Redis cache → warm cache survives restarts and scales horizontally |
| Cache backend hard-coded into the framework | `settings.toml` switches backends; new backends slot in via `CacheService` |
| Services that scaled out had to pin to one replica or accept duplicate work | Two replicas of the same service deduplicate work via the shared cache |
| Two different services on the same Redis would collide on identical keys | `key_prefix` per service guarantees isolation |
| No way to verify multi-instance behaviour without spinning up real replicas | `examples/shared_cache_demo/demo_multiprocess.py` proves cross-process sharing in 2 seconds |
| No automated test for "two services in one app share cache via the registry" | `tests/unit/agents/services/infrastructure/test_cache_sharing_via_registry.py` covers it |
| `Config.get_cache_config()` only read 4 of 11 fields (backend/redis_* ignored) | All fields are read; Redis is reachable purely through `settings.toml` |
| Redis outage → pod looks healthy to K8s, silently serves cache misses | Readiness probe flips to HTTP 503 within one health-check interval; K8s drops pod from service pool until Redis recovers |
