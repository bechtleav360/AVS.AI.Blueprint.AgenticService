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
