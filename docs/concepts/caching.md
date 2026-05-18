# Caching

Blueprint Agents includes a built-in persistent key-value cache backed by diskcache-rs. The cache provides fast local storage with TTL expiration, namespace isolation, and a management REST API.

## Enabling the Cache

Enable caching by calling `.with_cache()` on the `AppBuilder`:

```python
from blueprint.agents import AppBuilder, Config

config = Config(settings_files=["settings.toml", "secrets.toml"])

app = (
    AppBuilder(config)
    .with_service(MyService)
    .with_handler(MyHandler)
    .with_cache()
    .build()
)
```

Once enabled, the cache service is registered in the component registry and a management REST API is automatically mounted.

## Accessing the Cache

The cache is available through the component registry from `on_startup()` onward:

```python
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import CloudEvent, HandlerResult


class DeduplicationHandler(EventHandlerBase):
    priority = 1

    async def on_startup(self) -> None:
        self.cache = self.registry.cache_service

    def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        return event.type == "document.received"

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> HandlerResult | None:
        doc_id = event.subject

        # Check if already processed
        if await self.cache.get(doc_id, namespace="processed"):
            return None  # Skip duplicate

        # Mark as processed with a 1-hour TTL
        await self.cache.set(doc_id, True, namespace="processed", ttl=3600)

        return HandlerResult(
            event_type="document.accepted",
            data=event.data,
        )
```

## Cache Operations

### get(key, namespace)

Retrieve a value by key within a namespace. Returns `None` if the key does not exist or has expired.

```python
value = await self.cache.get("user:12345", namespace="profiles")
if value is None:
    # Cache miss -- fetch from source
    value = await self.fetch_profile(12345)
    await self.cache.set("user:12345", value, namespace="profiles", ttl=900)
```

### set(key, value, namespace, ttl)

Store a value under a key. The `ttl` parameter specifies the time-to-live in seconds. If omitted, the `default_ttl` from configuration is used.

```python
# Cache for 30 minutes
await self.cache.set("result:abc", {"score": 0.95}, namespace="results", ttl=1800)

# Cache using the default TTL from settings.toml
await self.cache.set("result:def", {"score": 0.87}, namespace="results")
```

### delete(key, namespace)

Remove a specific key from a namespace.

```python
await self.cache.delete("user:12345", namespace="profiles")
```

### clear(namespace)

Remove all entries in a namespace. Useful for bulk invalidation.

```python
# Purge all cached search results
await self.cache.clear(namespace="search_results")
```

## TTL and Automatic Expiration

Every cached entry can have an individual TTL (time-to-live) in seconds. Once the TTL elapses, the entry is no longer returned by `get()` and is eligible for eviction.

```python
# Short-lived cache for rate limiting (60 seconds)
await self.cache.set(f"rate:{client_ip}", request_count, namespace="rate_limit", ttl=60)

# Long-lived cache for expensive computations (24 hours)
await self.cache.set(embedding_key, vector, namespace="embeddings", ttl=86400)
```

If no TTL is provided, the `default_ttl` value from `[default.cache]` in `settings.toml` is applied.

## Namespace Isolation

Namespaces partition the cache into logical segments. Different components can use separate namespaces without risk of key collisions.

```python
# Handler uses one namespace
await self.cache.set("doc:1", metadata, namespace="documents")

# Service uses a different namespace
await self.cache.set("doc:1", embedding, namespace="embeddings")

# No collision -- these are independent entries
```

Namespaces also allow targeted invalidation. Clearing one namespace does not affect others.

## Key Hashing for Complex Keys

The cache supports complex keys such as lists, dictionaries, and tuples. These are automatically hashed to produce a stable string key.

```python
# Dictionary key -- automatically hashed
query_params = {"model": "gpt-4o", "prompt": "Summarize this document", "temperature": 0.3}
cached_response = await self.cache.get(query_params, namespace="llm_responses")

if cached_response is None:
    response = await self.call_llm(query_params)
    await self.cache.set(query_params, response, namespace="llm_responses", ttl=7200)

# List key -- also automatically hashed
chunk_ids = ["chunk-a", "chunk-b", "chunk-c"]
await self.cache.set(chunk_ids, merged_result, namespace="merged_chunks")
```

## Cache Management REST API

When the cache is enabled, the framework automatically registers a REST API for cache inspection and management at `/api/cache`.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/cache/{namespace}/{key}` | Retrieve a cached value |
| `PUT` | `/api/cache/{namespace}/{key}` | Set a cached value (JSON body) |
| `DELETE` | `/api/cache/{namespace}/{key}` | Delete a cached entry |
| `DELETE` | `/api/cache/{namespace}` | Clear an entire namespace |

### Example Usage

```bash
# Retrieve a cached value
curl http://localhost:8000/api/cache/profiles/user:12345

# Set a cached value with a TTL
curl -X PUT http://localhost:8000/api/cache/results/query:abc \
  -H "Content-Type: application/json" \
  -d '{"value": {"score": 0.95}, "ttl": 1800}'

# Delete a specific key
curl -X DELETE http://localhost:8000/api/cache/profiles/user:12345

# Clear all entries in a namespace
curl -X DELETE http://localhost:8000/api/cache/search_results
```

## Configuration

Cache settings are defined in `settings.toml` under the `[default.cache]` section:

```toml
[default.cache]
cache_dir = "/tmp/blueprint-cache"
size_limit = 1073741824              # Maximum cache size in bytes (1 GB)
eviction_policy = "least-recently-used"  # Eviction strategy when size_limit is reached
default_ttl = 3600                   # Default TTL in seconds (1 hour)
```

### Configuration Fields

| Field | Type | Description |
|---|---|---|
| `cache_dir` | `str` | Filesystem path where cache data is stored |
| `size_limit` | `int` | Maximum total cache size in bytes |
| `eviction_policy` | `str` | Strategy for removing entries when the cache is full |
| `default_ttl` | `int` | Default time-to-live in seconds for entries without an explicit TTL |

## Redis Backend

For deployments where multiple service instances need to share cache state (e.g. horizontal scaling, blue/green deployments, multi-pod Kubernetes setups), Blueprint Agents ships with an optional Redis backend. Cache reads and writes flow through a central Redis server so every replica sees the same data.

### Installation

The Redis client is an optional extra. Install it explicitly:

```bash
pip install 'avs-blueprint-agents[redis]'
```

This pulls in `redis-py` with the `hiredis` parser for fast wire-protocol decoding. No code changes are required — the framework auto-selects the backend at startup based on `settings.toml`.

### Configuration

Switch backends by setting `backend = "redis"` and adding the connection fields:

```toml
[default.cache]
backend = "redis"                         # "disk" (default) or "redis"
default_ttl = 3600                        # Default TTL in seconds (used by both backends)
key_prefix = "inventory-api"              # Prefix prepended to every cache key
redis_url = "redis://localhost:6379/0"    # Connection URL (host, port, db)
redis_password = "secret"                 # Optional password
redis_db = 0                              # Database index (0–15 for default Redis)
redis_tls = false                         # Set true for TLS (rediss://)
fallback_to_local = false                 # If true: fall back to DiskCacheService when Redis is unreachable
```

### Field Reference

| Field | Type | Description |
|---|---|---|
| `backend` | `str` | `"disk"` (default) or `"redis"`. Controls which cache implementation is instantiated. |
| `key_prefix` | `str` | Global prefix prepended to every key in the form `{prefix}:{namespace}:{hash}`. Lets you safely share a single Redis database between multiple services without key collisions. Empty string disables prefixing. |
| `redis_url` | `str` | Standard Redis URL (`redis://...` or `rediss://...` for TLS). Defaults to `redis://localhost:6379/0`. |
| `redis_password` | `str \| None` | Password for Redis AUTH. Read this from a secrets file, never commit it. |
| `redis_db` | `int` | Numeric database index. Default is `0`. |
| `redis_tls` | `bool` | Enable TLS — equivalent to using `rediss://` in `redis_url`. |
| `fallback_to_local` | `bool` | If `True`, the framework starts up with `DiskCacheService` when (a) the Redis extra is not installed or (b) the Redis server is unreachable on `on_startup()`. Useful for graceful degradation in non-production environments. |

### Multi-Service Shared Redis

When several microservices share one Redis cluster, set a unique `key_prefix` per service:

```toml
# Service A
[default.cache]
backend = "redis"
key_prefix = "inventory-api"
redis_url = "redis://shared-redis:6379/0"

# Service B
[default.cache]
backend = "redis"
key_prefix = "billing-api"
redis_url = "redis://shared-redis:6379/0"
```

Each service's `clear()`, `list_namespaces()`, and `list_values()` calls only operate within its own prefix. `clear()` uses `SCAN` + `DELETE` (never `FLUSHDB`), so it never touches keys belonging to other services.

### Graceful Degradation

In development or non-critical environments, set `fallback_to_local = true` to keep the service running when Redis is unavailable:

```toml
[default.cache]
backend = "redis"
redis_url = "redis://localhost:6379/0"
fallback_to_local = true
```

Behavior:
- If the `redis` extra is not installed: factory returns a `DiskCacheService`.
- If Redis is installed but unreachable on startup: `on_startup()` logs the failure and continues without raising.

In production, leave `fallback_to_local = false` so startup fails loudly when the cache backend is misconfigured.

## File-Based Locking

The DiskCacheService uses file-based locking to ensure safe concurrent access across multiple processes or deployment replicas sharing the same `cache_dir`. This means multiple instances of the same service can safely read and write to a shared cache directory without corruption.

```toml
[default.cache]
# Shared cache directory across replicas
cache_dir = "/mnt/shared/blueprint-cache"
```

## Complete Example

```python
from blueprint.agents import AppBuilder, Config
from blueprint.agents.services.service_base import ServiceBase
from blueprint.agents.handler.event_handler_base import EventHandlerBase
from blueprint.agents.models.events import CloudEvent, HandlerResult


class EmbeddingService(ServiceBase):
    async def on_startup(self) -> None:
        self.cache = self.registry.cache_service
        self.agent = self.registry.get_agent("embedder")

    async def get_embedding(self, text: str) -> list[float]:
        # Check cache first
        cached = await self.cache.get(text, namespace="embeddings")
        if cached is not None:
            return cached

        # Compute and cache
        embedding = await self.agent.run(text)
        await self.cache.set(text, embedding, namespace="embeddings", ttl=86400)
        return embedding


class DocumentHandler(EventHandlerBase):
    priority = 10

    async def on_startup(self) -> None:
        self.embedding_svc = self.registry.get_service(EmbeddingService)

    def can_handle_event(self, event: CloudEvent) -> bool:
        return event.type == "document.received"

    async def handle_event(self, event: CloudEvent) -> HandlerResult:
        embedding = await self.embedding_svc.get_embedding(event.data["content"])
        return HandlerResult(
            event_type="document.embedded",
            data={"doc_id": event.subject, "embedding": embedding},
        )

    def get_published_event_types(self) -> list[str]:
        return ["document.embedded"]


config = Config(settings_files=["settings.toml"])

app = (
    AppBuilder(config)
    .with_service(EmbeddingService)
    .with_handler(DocumentHandler)
    .with_agent("embedder", EmbedderAgent)
    .with_cache()
    .build()
)
```
