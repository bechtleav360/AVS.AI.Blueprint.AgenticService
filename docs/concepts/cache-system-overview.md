# Cache System Overview

A diagram-led tour of how the cache is structured, where the **Strategy pattern** sits, and how data flows from a service call to a Redis key.

For the design rationale, see [Cache Architecture](./cache-architecture.md). For setup steps, see [Caching — Getting Started](../guides/caching-getting-started.md).

---

## Strategy pattern in one picture

The cache is a textbook Strategy pattern. The **context** (the calling code) holds a reference to a **strategy** (a `CacheService`) and uses it through a fixed interface. The concrete strategy is selected once, at startup, by a factory that reads configuration.

```
                ┌──────────────────────────────────────────────┐
                │  Context: any service, handler, or API       │
                │                                              │
                │      self._cache = self.registry             │
                │                       .cache_service         │
                │                                              │
                │      self._cache.set("k", v, namespace="ns") │
                │      self._cache.get("k", namespace="ns")    │
                └──────────────────────┬───────────────────────┘
                                       │ uses
                                       ▼
                ┌──────────────────────────────────────────────┐
                │  Strategy interface: CacheService            │
                │                                              │
                │     get(key, namespace) -> Any | None        │
                │     set(key, value, namespace, ttl) -> None  │
                │     delete(key, namespace) -> bool           │
                │     exists(key, namespace) -> bool           │
                │     clear(namespace) -> None                 │
                └────────┬─────────────────────────────┬───────┘
                         │ implemented by              │
                         ▼                             ▼
            ┌────────────────────────┐   ┌─────────────────────────┐
            │ ConcreteStrategy:       │   │ ConcreteStrategy:        │
            │ DiskCacheService        │   │ RedisCacheService        │
            │                         │   │                          │
            │ • diskcache-rs (Rust)   │   │ • redis-py 7.x           │
            │ • file-system, local    │   │ • TCP, shared            │
            │ • per-process           │   │ • across processes       │
            └────────────────────────┘   └─────────────────────────┘
                         ▲                             ▲
                         │                             │
                         │ chooses one of these        │
                         │                             │
                         └──────────────┬──────────────┘
                                        │
                                        │ creates
                              ┌─────────┴─────────────┐
                              │   CacheBackendFactory  │
                              │                        │
                              │   if config.backend    │
                              │      == "redis":       │
                              │       RedisCacheService│
                              │   else:                │
                              │       DiskCacheService │
                              └─────────┬──────────────┘
                                        │ reads
                                        ▼
                              ┌────────────────────────┐
                              │  CacheConfig (Pydantic) │
                              │                         │
                              │  backend, redis_url,    │
                              │  key_prefix, …          │
                              └─────────┬──────────────┘
                                        │ produced by
                                        ▼
                              ┌────────────────────────┐
                              │  Config.get_cache_      │
                              │       config()          │
                              │                         │
                              │  reads [default.cache]  │
                              │  from settings.toml     │
                              │  via Dynaconf           │
                              └────────────────────────┘
```

**Why this matters**: a service that calls `self._cache.set(...)` has no idea — and does not need to know — whether that write goes to a local `.cache/` folder or to a Redis cluster on the other side of the world. Switching backends is a one-line change in `settings.toml`.

---

## Lifecycle: from `AppBuilder.build()` to a Redis key

The end-to-end timeline of one cache write, from app startup through the actual Redis command:

```
   APP STARTUP
   ───────────

      AppBuilder(config)                          [1]
        .with_service(PricingService)             [2]
        .with_service(RecommendationService)      [3]
        .with_cache()                             [4]
        .build()                                  [5]


   [4]  with_cache()                              [5]  build() → on_startup()
        ─────────────                                  ────────────────────────

        Config.get_cache_config()                      For every component:
                ↓                                           component.on_startup()
        CacheConfig(                                          ↓
          backend="redis",                                Pricing  ← registry.cache_service
          redis_url="redis://...",                        Recommend ← registry.cache_service
          key_prefix="my-svc",                            (both get the SAME instance)
          ...
        )
                ↓
        CacheBackendFactory.create(cfg)
                ↓
        RedisCacheService(redis_url=..., key_prefix=...)
                ↓
        Component.shared_registry.cache_service = ↑


   APP RUNTIME
   ───────────

      PricingService.store_price("laptop", 49.99)
              ↓
        self._cache.set(
            "price:laptop",
            {"amount": 49.99},
            namespace="products",
            ttl=600
        )
              ↓
        RedisCacheService._full_key(...)         →  "my-svc:products:7f8a…"
              ↓
        json.dumps({"amount": 49.99})            →  '{"amount": 49.99}'
              ↓
        redis_client.set(
            "my-svc:products:7f8a…",             ←  SET command on Redis
            '{"amount": 49.99}',
            ex=600                               ←  Redis-native TTL
        )

      RecommendationService.read_price("laptop")
              ↓
        self._cache.get("price:laptop", namespace="products")
              ↓
        RedisCacheService._full_key(...)         →  "my-svc:products:7f8a…"  (same hash!)
              ↓
        redis_client.get("my-svc:products:7f8a…")
              ↓
        '{"amount": 49.99}'  →  json.loads()  →  {"amount": 49.99}
```

The key insight: both services produce the **same** Redis key from the same logical key, namespace, and prefix. That's how they see each other's writes through the registry.

---

## Multi-process / multi-replica view

This is the case the issue asks for. Two replicas of the same service running in two different processes (or two different pods) — both connected to one Redis:

```
   ┌─────────────────────────────┐         ┌─────────────────────────────┐
   │  Replica A (PID 1234)        │         │  Replica B (PID 5678)        │
   │                              │         │                              │
   │   Component.shared_registry  │         │   Component.shared_registry  │
   │   ┌────────────────────────┐ │         │   ┌────────────────────────┐ │
   │   │ cache_service:          │ │         │   │ cache_service:          │ │
   │   │   RedisCacheService    │ │         │   │   RedisCacheService    │ │
   │   │   (instance #A)        │ │         │   │   (instance #B)        │ │
   │   │                        │ │         │   │                        │ │
   │   │   key_prefix="my-svc"  │ │         │   │   key_prefix="my-svc"  │ │
   │   └─────────┬──────────────┘ │         │   └─────────┬──────────────┘ │
   │             │                │         │             │                │
   └─────────────┼────────────────┘         └─────────────┼────────────────┘
                 │ TCP                                    │ TCP
                 │                                        │
                 └────────────────┬───────────────────────┘
                                  ▼
                       ┌──────────────────────┐
                       │  Redis                │
                       │                       │
                       │  my-svc:ns:hash1 ───┐│
                       │                     ││ shared
                       │  my-svc:ns:hash2 ───┘│
                       │                       │
                       └──────────────────────┘
```

Each replica owns its own `RedisCacheService` Python object and its own TCP connection to Redis. They have **no shared memory and no shared Python objects**. The only shared state is Redis itself, which is exactly what makes the cache "centralised".

This is what `examples/shared_cache_demo/demo_multiprocess.py` demonstrates programmatically (using two `multiprocessing.Process` workers to simulate the two replicas).

---

## Data layout in Redis

Every cache write goes through the same key formula:

```
   ┌────────────────┬──────────────┬──────────────────────────────┐
   │  key_prefix    │  namespace   │  sha256(normalised key)      │
   ├────────────────┼──────────────┼──────────────────────────────┤
   │  "my-svc"      │  "products"  │  "7f8a9c1e2b…"               │
   └────────────────┴──────────────┴──────────────────────────────┘
            │              │                    │
            └──────────────┴────────────────────┘
                           │
                           ▼
                     "my-svc:products:7f8a9c1e2b…"
```

- **`key_prefix`** isolates whole services from each other (e.g. `payments-svc` vs. `inventory-svc`).
- **`namespace`** isolates logical groups within one service (e.g. `prices` vs. `recommendations`).
- **`hash`** is the SHA-256 of the key, after JSON-normalising it so that `["a", "b"]` and `["b", "a"]` produce the same hash, and `{"x": 1, "y": 2}` and `{"y": 2, "x": 1}` produce the same hash.

The two-layer prefix system means **multiple services can share one Redis without ever colliding**, and within a service you can subdivide cleanly by namespace.

---

## Component responsibilities at a glance

| Component | Role | Knows about | Does NOT know about |
|---|---|---|---|
| `CacheService` | Interface every backend implements | – | Concrete backends |
| `DiskCacheService` | Local disk-backed implementation | `diskcache-rs`, file system | Redis, Dynaconf, AppBuilder |
| `RedisCacheService` | Redis-backed implementation | `redis-py`, key-prefix scheme | DiskCache, Dynaconf, AppBuilder |
| `CacheBackendFactory` | Strategy selector | Both backends, `CacheConfig` | Settings files, AppBuilder |
| `CacheConfig` | Typed Pydantic config model | Field shapes only | Dynaconf, AppBuilder, backends |
| `Config.get_cache_config()` | Reads `[default.cache]` from settings | Dynaconf, `CacheConfig` | Backends, registry |
| `AppBuilder.with_cache()` | Wires the cache into the registry | Factory, registry, `Config` | Backends |
| `Component.shared_registry` | Singleton store, dependency lookup | `CacheService` (interface only) | Backends, settings |
| Application services | Use the cache through `self.registry.cache_service` | The interface | Everything else |

Each layer touches only the layers immediately above and below it. This is what makes the architecture extensible: add a new backend by implementing `CacheService` + extending the factory, and nothing else has to change.
