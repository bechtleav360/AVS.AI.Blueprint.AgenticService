# Caching — Getting Started

This guide walks a developer who is **already using `avs-blueprint-agents`** through enabling the centralised Redis cache for their service. Estimated time: 5 minutes once Redis is reachable.

For the architectural background, see [Cache Architecture](../concepts/cache-architecture.md).

---

## 1. Add the Redis extra to your project

The `redis` Python package is shipped as an **optional extra** of `avs-blueprint-agents` so single-replica deployments don't pull in extra dependencies.

In your project's `pyproject.toml`:

```toml
[project]
dependencies = [
    "avs-blueprint-agents[redis]>=0.6.0",
    # ... your other dependencies
]
```

If you use `requirements.txt`:

```
avs-blueprint-agents[redis]>=0.6.0
```

If you use `uv`:

```bash
uv add "avs-blueprint-agents[redis]"
```

What this pulls in: `redis>=5.0.0` with the `hiredis` C-parser for performance.

---

## 2. Tell the blueprint which backend to use

In your `settings.toml` (or whichever Dynaconf settings file you use):

```toml
[default.cache]
backend       = "redis"                      # was "disk" — switch here
key_prefix    = "my-service-name"            # avoids collisions in shared Redis
redis_url     = "redis://localhost:6379/0"   # full URL incl. db index
default_ttl   = 600                          # seconds; null = no expiry

# --- Optional ---
# redis_password    = "@format {env[REDIS_PASSWORD]}"
# redis_db          = 0
# redis_tls         = false                  # true → uses rediss:// scheme
# fallback_to_local = false                  # true → fallback to DiskCache if Redis is down
```

**That's the only required change.** Your existing `AppBuilder().with_cache()` line picks up the new config automatically — no code change.

### Required vs. optional fields

| Field | Required? | Default | Notes |
|---|---|---|---|
| `backend` | yes (to switch) | `"disk"` | `"disk"` or `"redis"` |
| `redis_url` | yes for Redis | `"redis://localhost:6379/0"` | Standard URL, `redis://[user[:password]]@host:port/db` |
| `key_prefix` | recommended | `""` | Pick something distinctive per service — avoids collisions when multiple services share Redis |
| `default_ttl` | optional | `3600` | Seconds; `null` means no TTL is set on writes that don't supply one |
| `redis_password` | only if needed | `null` | Use Dynaconf env-var injection: `"@format {env[REDIS_PASSWORD]}"` |
| `redis_db` | optional | `0` | Redis DB index; usually `0` |
| `redis_tls` | only for TLS | `false` | When `true`, the connection upgrades to `rediss://` |
| `fallback_to_local` | optional | `false` | Soft fallback when Redis is unreachable at startup |

---

## 3. Use the cache from your services

Nothing changes here. Every service / handler / API resolves the cache from the registry in `on_startup()`:

```python
from blueprint.agents.services.service_base import ServiceBase

class MyService(ServiceBase):
    async def on_startup(self) -> None:
        self._cache = self.registry.cache_service

    async def on_shutdown(self) -> None:
        return None

    def remember(self, key: str, value: dict) -> None:
        self._cache.set(key, value, namespace="my-namespace")

    def recall(self, key: str) -> dict | None:
        return self._cache.get(key, namespace="my-namespace")
```

The `self._cache` you receive is the **same instance** for every service in this app — that's what makes "two agents writing to the same cache" work.

---

## 4. Verify it works

Run a real Redis (Docker is fine):

```bash
docker run -d --rm --name dev-redis -p 6379:6379 redis:alpine
```

Start your app:

```bash
python -m uvicorn src.main:app --port 8000
```

You should see in the log:

```
Adding component: redis_cache_service to registry
Registering cache service: RedisCacheService
RedisCacheService connected to redis://localhost:6379/0 (prefix='my-service-name')
```

Hit any endpoint that writes to the cache, then peek at Redis to see your keys:

```bash
docker exec dev-redis redis-cli KEYS "my-service-name:*"
```

You should see one or more keys like `my-service-name:my-namespace:<sha256>`.

---

## 5. Multiple replicas — the actual point of the feature

The whole reason for switching to Redis is **shared state across replicas**. To prove it works in your setup:

```bash
# Terminal 1 — replica A
python -m uvicorn src.main:app --port 8001

# Terminal 2 — replica B (same code, same settings.toml, different port)
python -m uvicorn src.main:app --port 8002

# Write to replica A
curl -X POST 'http://localhost:8001/your-write-endpoint?...'

# Read on replica B — should return what A just wrote
curl 'http://localhost:8002/your-read-endpoint'
```

If A's writes show up on B, you're done. If not, double-check `key_prefix` and `redis_url` are identical between the two replicas.

---

## 6. Operations checklist

Before you ship to production:

- [ ] Use a managed Redis (or your platform's Redis service) — don't run `redis:alpine` in prod
- [ ] Set `redis_password` via env var, not literally in `settings.toml`
- [ ] Use TLS for any Redis that is not in the same VPC: `redis_tls = true`
- [ ] Pick a `key_prefix` that includes the service name *and* environment (e.g. `payments-svc-prod`)
- [ ] Decide on `fallback_to_local`: ON keeps the service up if Redis is down, OFF surfaces the issue immediately. Both are valid — choose the one that matches your operational posture
- [ ] Set `default_ttl` so abandoned keys eventually disappear
- [ ] Wire K8s probes to `/health/ready` (readiness) and `/health/live` (liveness) — the framework reflects Redis reachability via the readiness probe automatically

### How the readiness probe interacts with Redis outages

When `with_cache()` is called, a `CacheHealthChecker` is registered automatically and pings Redis on every health-check tick (default 30 s, configurable via `health_check_interval_seconds`).

| Scenario | `/health/ready` | `/health/live` | K8s reaction |
|---|---|---|---|
| Redis healthy | `200 UP` with `cache: healthy` | `200 UP` | Pod in service pool, traffic flows |
| Redis stops mid-flight | Within ≤ 30 s flips to `503 DOWN` with full diagnostic payload | stays `200 UP` | Pod removed from service pool, **not** killed |
| Redis recovers | Within ≤ 30 s flips back to `200 UP` | stays `200 UP` | Pod re-added to service pool automatically |
| `fallback_to_local=true`, Redis unreachable at startup | `503 DOWN` once first health tick runs | `200 UP` | Pod alive but won't take traffic until Redis returns |
| `fallback_to_local=false`, Redis unreachable at startup | never reached (boot crashes) | never reached | CrashLoopBackOff → pager |

A K8s `httpGet` probe on `/health/ready` only inspects the HTTP status code, so the 503 propagation is what makes the cache check actually take effect at the orchestration layer.

Example K8s probe configuration:

```yaml
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 10   # give the cache health check one tick
  periodSeconds: 10
  failureThreshold: 3       # tolerate one missed tick before pulling the pod
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError: Redis backend requires 'avs-blueprint-agents[redis]'` | Forgot to install the extra | `pip install 'avs-blueprint-agents[redis]'` |
| Log shows `DiskCacheService` instead of `RedisCacheService` | `settings.toml` not picked up — wrong path or wrong section | Confirm `[default.cache]` section, confirm `Config(settings_files=["settings.toml"])` finds the file |
| `redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379` | Redis not running | `docker ps` to check; `docker run -d -p 6379:6379 redis:alpine` to start |
| Two replicas don't see each other's keys | Different `key_prefix` between replicas | Identical `key_prefix` for replicas of the same service |
| Two services collide on the same key | Same `key_prefix` for different services | Pick distinct `key_prefix` values per service |
| `Component with name redis_cache_service already exists` (in tests) | A previous test already constructed a cache and the Component registry rejects duplicate names | Use the autouse fixture pattern from `tests/integration/test_shared_redis_cache.py` to clear the registry between tests |
