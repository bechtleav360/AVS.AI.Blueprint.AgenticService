# Caching Guide

This guide explains how to enable and use the persistent caching layer in your agent applications.

## Overview

The caching system provides:

- **Persistent disk-based storage** - Data survives application restarts
- **High performance** - Rust-backed implementation via `diskcache-rs`
- **TTL support** - Automatic expiration of cached entries
- **Flexible key types** - Support for strings, lists, and dicts
- **JSON-aware hashing** - Consistent hashing regardless of key order
- **Namespace isolation** - Organize cache entries by namespace

## Enabling Caching

### 1. Enable in AppBuilder

The simplest way to enable caching is through the `AppBuilder`:

```python
from blueprint.agents import AppBuilder, Config

config = Config(settings_files=["settings.toml"])

app = (
    AppBuilder(config)
    .with_cache(enabled=True)  # Enable persistent caching
    .with_handler(MyHandler)
    .build()
)
```

### 2. Configure via Settings

Customize cache behavior in your `settings.toml`:

```toml
[cache]
cache_dir = ".cache/blueprint"           # Cache directory path
size_limit = 1000000000                  # 1GB max size
eviction_policy = "least-recently-used"  # LRU eviction
default_ttl = 3600                       # 1 hour default TTL
```

All settings are optional and use sensible defaults.

## Using the Cache

### Access from Handlers

Get the cache service from the component registry:

```python
from blueprint.agents.base import EventHandler
from blueprint.agents.models import CloudEvent

class MyHandler(EventHandler):
    async def handle_event(self, event: CloudEvent, context: dict):
        # Get cache from registry
        cache = self._component_registry.get_cache()

        # Check if data is cached
        if cache.exists("user:123"):
            user = cache.get("user:123")
            return {"cached": True, "user": user}

        # Fetch data and cache it
        user = await fetch_user("123")
        cache.set("user:123", user, ttl=3600)  # Cache for 1 hour

        return {"cached": False, "user": user}
```

### Access from Services

Similarly, access cache from business services:

```python
from blueprint.agents.base import BusinessService

class UserService(BusinessService):
    async def get_user(self, user_id: str):
        cache = self._component_registry.get_cache()

        # Try cache first
        cached = cache.get(f"user:{user_id}")
        if cached:
            return cached

        # Fetch and cache
        user = await self._fetch_from_db(user_id)
        cache.set(f"user:{user_id}", user, ttl=3600)
        return user
```

## Key Types and Hashing

The cache intelligently handles different key types with consistent hashing:

### String Keys

```python
cache.set("simple_key", data)
cache.get("simple_key")
```

### List Keys

Lists are sorted before hashing, so order doesn't matter:

```python
# Both produce the same hash
cache.set(["user", "profile", "123"], data)
cache.get(["123", "profile", "user"])  # Retrieves same data!
```

### Dict Keys

Dicts are sorted by keys before hashing:

```python
# Both produce the same hash
cache.set({"user_id": "123", "type": "profile"}, data)
cache.get({"type": "profile", "user_id": "123"})  # Retrieves same data!
```

### JSON String Keys

JSON strings are automatically parsed and normalized:

```python
# All three produce the same hash
cache.set('{"user":"123","type":"profile"}', data)
cache.get('{"type":"profile","user":"123"}')  # Same hash!
cache.get({"user": "123", "type": "profile"})  # Same hash!
```

## Namespacing

Organize cache entries by namespace to avoid collisions:

```python
cache = registry.get_cache()

# Cache user data in "users" namespace
cache.set("123", user_data, namespace="users")

# Cache product data in "products" namespace
cache.set("456", product_data, namespace="products")

# Clear only user cache
cache.clear(namespace="users")

# Clear entire cache
cache.clear()
```

## TTL (Time-To-Live)

Set expiration times for cache entries:

```python
cache = registry.get_cache()

# Cache for 1 hour (3600 seconds)
cache.set("key", data, ttl=3600)

# Cache with no expiration
cache.set("key", data)

# Check if key exists (respects TTL)
if cache.exists("key"):
    value = cache.get("key")
```

Expired entries are automatically cleaned up when accessed.

## Cache Statistics

Monitor cache usage:

```python
cache = registry.get_cache()

stats = cache.get_stats()
print(f"Cache size: {stats['size']} entries")
print(f"Cache directory: {stats['cache_dir']}")
print(f"TTL tracked keys: {stats['ttl_tracked_keys']}")
```

## Common Patterns

### Lazy Loading with Cache

```python
async def get_user(user_id: str):
    cache = registry.get_cache()

    # Try cache first
    user = cache.get(f"user:{user_id}")
    if user:
        return user

    # Load from source
    user = await fetch_user(user_id)
    cache.set(f"user:{user_id}", user, ttl=3600)
    return user
```

### Cache Invalidation

```python
async def update_user(user_id: str, data: dict):
    cache = registry.get_cache()

    # Update in database
    updated = await db.update_user(user_id, data)

    # Invalidate cache
    cache.delete(f"user:{user_id}")

    return updated
```

### Batch Operations

```python
async def get_users(user_ids: list[str]):
    cache = registry.get_cache()
    results = []

    for user_id in user_ids:
        # Check cache
        user = cache.get(f"user:{user_id}")
        if not user:
            # Load and cache
            user = await fetch_user(user_id)
            cache.set(f"user:{user_id}", user, ttl=3600)
        results.append(user)

    return results
```

## Disabling Cache

To disable caching:

```python
app = (
    AppBuilder(config)
    .with_cache(enabled=False)  # Disable caching
    .with_handler(MyHandler)
    .build()
)
```

Or check if cache is available before using:

```python
if registry.has_cache():
    cache = registry.get_cache()
    # Use cache
else:
    # Fallback without cache
    pass
```

## Performance Considerations

- **Cache hits are fast** - Direct disk access via diskcache-rs
- **TTL checking is lazy** - Expiration checked only on access
- **Serialization is efficient** - Binary format optimized for speed
- **Thread-safe** - Safe to use from multiple threads/async tasks

## Troubleshooting

### Cache directory permission errors

Ensure the cache directory is writable:

```python
from pathlib import Path

cache_dir = Path(".cache/blueprint")
cache_dir.mkdir(parents=True, exist_ok=True)
```

### Cache not persisting

Verify the cache directory path in settings:

```toml
[cache]
cache_dir = ".cache/blueprint"  # Must be absolute or relative to working directory
```

### Memory usage growing

Set appropriate `size_limit` in settings:

```toml
[cache]
size_limit = 1000000000  # 1GB limit
```

When limit is reached, least-recently-used entries are evicted.

## Next Steps

- See [Configuration Guide](./configuration/) for advanced settings
- See [App Builder Guide](./app-builder.md) for more builder patterns
- See [Testing Guide](./testing.md) for cache testing strategies
