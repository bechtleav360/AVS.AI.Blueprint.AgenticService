# Concept: Caching

Learn how to use the persistent caching layer to improve performance.

---

## What is Caching?

Caching stores expensive computation results so you don't have to repeat them. Instead of calling an API or database every time, you return the cached result.

**Example:** If you call an LLM to analyze an invoice, cache the result. Next time someone analyzes the same invoice, return the cached result instantly.

---

## Enable Caching

### Step 1: Configure Settings

**File:** `settings.toml`

```toml
[default.cache]
cache_dir = ".cache/blueprint"           # Where to store cache files
size_limit = 1000000000                  # 1GB max size
eviction_policy = "least-recently-used"  # Remove oldest items when full
default_ttl = 3600                       # 1 hour expiration
```

### Step 2: Enable in AppBuilder

```python
app = (
    AppBuilder(config)
    .with_cache()  # Enable caching
    .build()
)
```

---

## Using the Cache

### Basic Usage

```python
from blueprint.agents import BusinessService

class InvoiceService(BusinessService):
    def get_name(self) -> str:
        return "invoice_service"

    async def analyze_invoice(self, invoice_text: str) -> dict:
        # Get cache from registry
        cache = self._component_registry.get_cache()

        # Create a cache key
        cache_key = cache.hash(invoice_text)

        # Check if result is cached
        cached_result = cache.get("invoices", cache_key)
        if cached_result:
            return cached_result

        # If not cached, do the expensive work
        result = await self._call_llm(invoice_text)

        # Store in cache with 1 hour TTL
        cache.set("invoices", cache_key, result, ttl=3600)

        return result
```

---

## Cache Keys

### Automatic Hashing

The cache automatically hashes keys for consistency:

```python
cache = self._component_registry.get_cache()

# String key
key1 = cache.hash("user:123")

# List key (order doesn't matter)
key2 = cache.hash(["user", "123"])

# Dict key (order doesn't matter)
key3 = cache.hash({"user_id": 123, "type": "invoice"})

# JSON string (automatically parsed and sorted)
key4 = cache.hash('{"user_id": 123, "type": "invoice"}')
```

### Key Consistency

These all produce the **same** hash:

```python
cache.hash({"a": 1, "b": 2})
cache.hash({"b": 2, "a": 1})
cache.hash('{"a": 1, "b": 2}')
cache.hash('{"b": 2, "a": 1}')
```

---

## Namespaces

Organize cache entries by namespace:

```python
cache = self._component_registry.get_cache()

# Store in "users" namespace
cache.set("users", key, user_data)

# Store in "invoices" namespace
cache.set("invoices", key, invoice_data)

# Retrieve from namespace
user = cache.get("users", key)
invoice = cache.get("invoices", key)

# List all namespaces
namespaces = cache.list_namespaces()
# Returns: ["users", "invoices"]
```

---

## TTL (Time-to-Live)

Automatically expire cached entries:

```python
cache = self._component_registry.get_cache()

# Cache for 1 hour (3600 seconds)
cache.set("users", key, data, ttl=3600)

# Cache for 1 day
cache.set("invoices", key, data, ttl=86400)

# Cache forever (no expiration)
cache.set("config", key, data, ttl=None)

# Check if entry is expired
value = cache.get("users", key)  # Returns None if expired
```

---

## Cache Management API

### Get Cache Statistics

```bash
curl http://localhost:8000/api/cache/stats
```

**Response:**
```json
{
  "size": 42,
  "cache_dir": "/path/to/.cache/blueprint",
  "ttl_tracked_keys": 10,
  "size_limit": 1000000000,
  "eviction_policy": "least-recently-used"
}
```

### List Namespaces

```bash
curl http://localhost:8000/api/cache/namespaces
```

**Response:**
```json
{
  "namespaces": ["users", "invoices", "config"],
  "count": 3
}
```

### Clear Cache

Clear entire cache:
```bash
curl -X POST http://localhost:8000/api/cache/evict \
  -H "Content-Type: application/json" \
  -d '{}'
```

Clear specific namespace:
```bash
curl -X POST http://localhost:8000/api/cache/evict \
  -H "Content-Type: application/json" \
  -d '{"namespace": "users"}'
```

---

## Real-World Example

### Invoice Analyzer with Caching

```python
class InvoiceService(BusinessService):
    def get_name(self) -> str:
        return "invoice_service"

    async def analyze_invoice(self, invoice_text: str) -> dict:
        cache = self._component_registry.get_cache()
        agent = self._component_registry.get_agent("invoice_analyzer")

        # Create cache key from invoice text
        cache_key = cache.hash(invoice_text)

        # Try to get from cache
        cached = cache.get("invoices", cache_key)
        if cached:
            logger.info("Cache hit for invoice")
            return cached

        # Not in cache, analyze with AI
        logger.info("Cache miss, analyzing with AI")
        result = await agent.run(invoice_text)

        # Store in cache for 24 hours
        cache.set("invoices", cache_key, result.data, ttl=86400)

        return result.data
```

### Handler Using Cache

```python
class InvoiceHandler(EventHandler):
    async def can_handle_event(self, event: CloudEvent, context) -> bool:
        return event.get_type() == "invoice.submitted"

    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        data = event.get_data()

        service = self._component_registry.get_service("invoice_service")
        result = await service.analyze_invoice(data["content"])

        return HandlerResult(
            event_type="invoice.analyzed",
            data=result
        )
```

---

## Performance Tips

1. **Use appropriate TTL** — Don't cache forever if data changes
2. **Use namespaces** — Organize related cache entries
3. **Monitor cache size** — Check stats endpoint regularly
4. **Clear old data** — Periodically clear unused namespaces
5. **Hash complex keys** — Use `cache.hash()` for consistent keys

---

## Common Patterns

### Cache-Aside Pattern

```python
async def get_user(user_id: str):
    cache = self._component_registry.get_cache()

    # Try cache first
    cached = cache.get("users", user_id)
    if cached:
        return cached

    # Load from database
    user = await database.get_user(user_id)

    # Store in cache
    cache.set("users", user_id, user, ttl=3600)

    return user
```

### Invalidate on Update

```python
async def update_user(user_id: str, data: dict):
    cache = self._component_registry.get_cache()

    # Update database
    user = await database.update_user(user_id, data)

    # Invalidate cache
    cache.delete("users", user_id)

    return user
```

### Batch Operations

```python
async def get_users(user_ids: list[str]):
    cache = self._component_registry.get_cache()
    results = []

    for user_id in user_ids:
        cached = cache.get("users", user_id)
        if cached:
            results.append(cached)
        else:
            # Load from database
            user = await database.get_user(user_id)
            cache.set("users", user_id, user, ttl=3600)
            results.append(user)

    return results
```

---

## Troubleshooting

### Cache Not Working

1. Verify caching is enabled:
   ```python
   app = AppBuilder(config).with_cache().build()
   ```

2. Check cache directory exists:
   ```bash
   ls -la .cache/blueprint/
   ```

3. Verify cache is registered:
   ```python
   if self._component_registry.has_cache():
       cache = self._component_registry.get_cache()
   ```

### Cache Growing Too Large

1. Reduce `size_limit` in settings
2. Reduce `default_ttl` to expire entries faster
3. Clear old namespaces:
   ```bash
   curl -X POST http://localhost:8000/api/cache/evict \
     -d '{"namespace": "old_namespace"}'
   ```

---

## Next Steps

- [Response Handling](response-handling.md) — Parse and validate AI responses
- [Tools](tools.md) — Give agents functions to call
- [Exception Handling](exception-handling.md) — Handle errors gracefully
