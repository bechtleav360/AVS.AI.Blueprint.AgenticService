# Caching

A cache in Blueprint Agents is a persistent key-value store that an application **declares** and
the framework creates. It has TTL expiry, namespaces for partitioning keys, a readiness check, a
small management API, and two interchangeable backends: a local disk store (the default) and Redis
(for state shared between replicas).

This is the one document for the cache. It replaces four that overlapped and disagreed -- a cache
architecture note, a system overview, a Redis getting-started guide, and an earlier version of
this file; see the git history for those.

---

## Declaring a cache

`with_cache()` on the builder:

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

Like every `with_*` call, this **records a declaration and constructs nothing**. The backend is
chosen and the store opened by `build()`, which is also why a cache can be declared before any
configuration exists.

### Several caches

Call it again with a name:

```python
AppBuilder(config).with_cache().with_cache(name="sessions").build()
```

Each name gets its own store -- its own directory on disk, its own key prefix on Redis -- and a
component reads one back by name. There is deliberately **no fallback from an unknown name to the
default**: asking for a cache that was not declared raises, rather than quietly handing over some
other cache.

| Call | Meaning |
|---|---|
| `with_cache()` | The default cache, named `default` |
| `with_cache(name="sessions")` | A second cache called `sessions` |
| `with_cache(False)` | Declares nothing; caching off |
| `with_cache(True, False)` | The default cache with file locking disabled |

`name` is keyword-only and comes last, which is a constraint rather than a style choice:
`with_cache(False)` has always meant "no cache", and had `name` come first that call would have
become a cache named `False` with caching silently switched *on*.

---

## Using a cache

Resolve it in `on_startup`, never in `__init__` -- nothing is constructed until `build()` runs, so
a collaborator may not exist yet while a component is being constructed.

```python
class DeduplicationHandler(EventHandlerBase):
    async def on_startup(self) -> None:
        self.cache = self.registry.get_cache("sessions")   # a named cache
        self.default = self.registry.cache_service          # the default one

    async def handle_event(self, event: GenericCloudEvent, context: dict) -> HandlerResult | None:
        if self.cache.get(event.subject, namespace="processed"):
            return None                                     # already seen
        self.cache.set(event.subject, True, namespace="processed", ttl=3600)
        return HandlerResult(event_type="document.accepted", data=event.data)
```

**The cache interface is synchronous.** `get`, `set` and the rest are ordinary methods; they are
not awaited, even inside `async def`. Operations are sub-millisecond on both backends.

`self.registry` answers for the component's own agent, so `get_cache("sessions")` reaches this
agent's `sessions` cache and cannot reach anyone else's.

### Operations

| Method | What it does |
|---|---|
| `get(key, namespace="default")` | The value, or `None` if absent or expired |
| `set(key, value, namespace="default", ttl=None)` | Store a value. `ttl` in seconds |
| `delete(key, namespace="default")` | Remove one key; `True` if it was there |
| `exists(key, namespace="default")` | Whether the key is present and unexpired |
| `clear(namespace=None)` | Empty one namespace, or the whole cache |
| `claim(key, value, namespace="default", ttl=None)` | Store **only if absent**; `True` if this caller stored it |
| `hash(value)` | The key hash this cache would use |
| `get_stats()` | Backend statistics (see the management API below) |
| `list_namespaces()` | Namespaces currently holding entries |
| `list_values(namespace="default", limit=100, offset=0)` | Iterate stored values, paginated |

### `claim`: deciding which process does the work

`exists` followed by `set` is not a lock. Two callers racing on the same key both pass the
`exists` check before either `set` lands, and both then believe they hold it. `claim` is the
set-if-absent primitive that closes the race -- `SET NX EX` on Redis, `add` on a lock-protected
disk cache -- and it is what event deduplication and the scheduler tick use to pick one winner
among several replicas.

```python
if not self.cache.claim(event.id, "processing", namespace="dedup", ttl=600):
    return None          # another replica got there first
```

### Keys and namespaces

A key may be a string, a list of strings, or a dictionary. Lists are sorted and dictionaries are
key-sorted before hashing, so `["a", "b"]` and `["b", "a"]` are the same key, and so are
`{"x": 1, "y": 2}` and `{"y": 2, "x": 1}`.

```python
params = {"model": "gpt-4o", "prompt": "Summarise this", "temperature": 0.3}
answer = self.cache.get(params, namespace="llm_responses")
if answer is None:
    answer = self.call_llm(params)
    self.cache.set(params, answer, namespace="llm_responses", ttl=7200)
```

A **namespace** partitions keys *within one cache*. Two components can both write `doc:1` under
different namespaces without colliding, and `clear(namespace=...)` invalidates one group without
touching the others. The default namespace is `default`.

### TTL

Every write gets a TTL. When `ttl` is omitted the cache-wide `default_ttl` applies -- one hour
unless configured otherwise -- on both backends. `default_ttl` is an integer, so **there is no way
to configure "never expires"** through a settings file; pass a long `ttl` at the call instead.

---

## A cache belongs to the agent that declared it

When several agents share one process, a cache is private to the one that declared it. Two agents
may both declare `sessions` and they get **separate stores**: separate directories on disk,
separate key prefixes on Redis. A lookup never falls back to a neighbour's cache or to the root's,
because two independently written agents both asking for `sessions` would otherwise share one
store the moment they were grouped -- and only in production.

Nothing about this is visible in an agent's code. `self.registry.get_cache("sessions")` is what
the author writes whether the agent runs alone or beside five others.

Where the data goes:

| | Disk backend | Redis backend |
|---|---|---|
| Standalone, default cache | `<cache_dir>` | keys under `<key_prefix>` |
| Standalone, cache `sessions` | `<cache_dir>/sessions` | keys under `<key_prefix>:sessions` |
| Agent `orders`, default cache | `<cache_dir>/orders.default` | keys under `<key_prefix>:orders.default` |
| Agent `orders`, cache `sessions` | `<cache_dir>/orders.sessions` | keys under `<key_prefix>:orders.sessions` |

A named store is a **subdirectory** of `cache_dir` rather than a sibling, because a deployment may
mount its volume at `cache_dir` itself and nothing outside the mount can be created under
`readOnlyRootFilesystem`. See *Writable Cache Directory* in
[deployment.md](../guides/deployment.md).

A single-agent application is unaffected in every respect: same directory, same Redis keyspace,
same registry names it always had.

> **Upgrading:** the key layout changed when caches became per-agent. An application upgrading
> with a mounted disk cache or a persistent Redis sees its old entries as absent -- a cold cache,
> not an error.

---

## Configuration

Under `[default.cache]` in `settings.toml`:

```toml
[default.cache]
cache_dir = ".cache/blueprint"
size_limit = 1000000000                  # bytes
eviction_policy = "least-recently-used"
default_ttl = 3600                       # seconds
```

| Field | Type | Default | Applies to |
|---|---|---|---|
| `backend` | `str` | `"disk"` | `"disk"` or `"redis"` |
| `cache_dir` | `str` | `".cache/blueprint"` | disk |
| `size_limit` | `int` | `1000000000` | disk |
| `eviction_policy` | `str` | `"least-recently-used"` | disk |
| `default_ttl` | `int` | `3600` | both |
| `key_prefix` | `str` | `""` | redis |
| `redis_url` | `str \| None` | `redis://localhost:6379/0` | redis |
| `redis_password` | `str \| None` | `None` | redis -- read it from a secrets file |
| `redis_db` | `int` | `0` | redis |
| `redis_tls` | `bool` | `false` | redis |
| `fallback_to_local` | `bool` | `false` | redis |

In a group each agent may configure its own cache under its own scope, so one agent can run on
Redis beside a neighbour on disk:

```toml
[default.cache]                 # what every agent gets unless it says otherwise
backend = "disk"

[default.orders.cache]          # just the orders agent
backend = "redis"
redis_url = "redis://shared-redis:6379/0"
key_prefix = "orders-api"
```

---

## Backends

### Disk (default)

Backed by `diskcache-rs`, a Rust implementation of the diskcache format. Persists to
`cache_dir`, survives restarts, and uses file-based locking so replicas sharing one mounted
directory can read and write it safely. Nothing has to be installed and nothing has to be
configured.

### Redis

For state shared across replicas -- horizontal scaling, blue/green, several pods behind one
service. Install the extra:

```bash
pip install 'avs-blueprint-agents[redis]'
```

and switch backends in the settings file:

```toml
[default.cache]
backend = "redis"
redis_url = "redis://localhost:6379/0"
key_prefix = "inventory-api"
```

No code changes: `with_cache()` picks up the backend from configuration.

Every Redis key is `{key_prefix}:{namespace}:{sha256(key)}`, so several services can share one
Redis database as long as each sets a distinct `key_prefix`. `clear()` uses `SCAN` + `DELETE`
within the prefix and never `FLUSHDB`, so it cannot touch another service's keys.

**Startup is a real connection.** `build()` pings Redis while creating the cache, so a
`RedisCacheService` in the registry always means a Redis that answered. If the ping fails:

- with `fallback_to_local = true`, the framework logs a warning and uses a disk cache instead --
  a genuine backend swap, and the application runs on disk thereafter;
- with `fallback_to_local = false` (the default), startup fails. In production that is what you
  want: a pod that cannot reach its cache should crash-loop visibly rather than serve misses.

The same applies when the `redis` extra is not installed at all.

---

## Readiness

Every declared cache is added to the readiness probe, so a Redis outage takes the pod out of the
service pool instead of letting it serve cache misses while looking healthy.

| Cache | Readiness entry |
|---|---|
| The default cache | `cache` |
| A cache named `sessions` | `cache:sessions` |
| Agent `orders`, default cache | `orders.cache` |
| Agent `orders`, cache `sessions` | `orders.cache:sessions` |

`/health/ready` answers **503** with a diagnostic payload while any check is down; `/health/live`
is unaffected, so Kubernetes removes the pod from the service pool without killing it. Recovery is
automatic on the next health tick (`health_check_interval_seconds`, 30 seconds by default). For a
disk cache the check is trivially up -- a local filesystem does not fail the way a network service
does.

---

## The management API

Declaring a cache mounts a small management API. A standalone application serves it at
`/api/cache/*`; in a group each agent that declared a cache gets its own under
`/api/<agent>/cache/*`, so one agent's endpoint cannot report another's keys.

| Method | Path | Body / query | Answers |
|---|---|---|---|
| `GET` | `/api/cache/stats` | `?name=` | Backend statistics for one cache |
| `GET` | `/api/cache/namespaces` | `?name=` | `{"namespaces": [...], "count": n}` |
| `POST` | `/api/cache/evict` | `{"namespace": "ns"}` | Clears that namespace, or the whole cache when `namespace` is omitted |

`?name=` selects which of the agent's caches to act on and defaults to `default`, so a request
that names nothing reaches the cache a single-cache application has always had.

```bash
curl localhost:8000/api/cache/stats
curl 'localhost:8000/api/cache/stats?name=sessions'
curl localhost:8000/api/cache/namespaces
curl -X POST localhost:8000/api/cache/evict -H 'Content-Type: application/json' -d '{"namespace": "profiles"}'
```

Two failures, answered differently: **503** when the agent has no cache at all (it was built
without one, which may change without a redeploy), and **404** for a name that is not among the
ones it has -- a retry can never fix a typo. The 404 body lists the registered names, because
nothing else does.

**The statistics are the backend's own**, not a fixed schema. A disk cache reports its directory,
entry count, size limit and eviction policy; Redis reports a server version, client count, memory
and uptime. Fields the backend in use did not fill in are omitted.

```jsonc
// disk
{"size": 4, "cache_dir": "/var/cache/blueprint", "size_limit": 1000000000, "eviction_policy": "least-recently-used"}
// redis
{"backend": "redis", "key_prefix": "orders-api", "redis_version": "7.2.4", "connected_clients": 3, ...}
```

> `size` on the disk backend counts stored keys, and each cached value is stored with a parallel
> TTL entry -- so a cache holding two values reports `size: 4`. `list_values` and
> `list_namespaces` filter the TTL entries out; `size` does not.

---

## How it fits together

The cache is a Strategy: calling code holds a `CacheService` and uses it through a fixed
interface, and which implementation that is gets decided once, at build time, from configuration.

```
  settings.toml [default.cache] -- or [default.<agent>.cache] for one agent in a group
            |
            v
  Config.get_cache_config()  ->  CacheConfig (pydantic)
            |
            v
  CacheBackendFactory.create(config, name=..., namespace=...)
            |                     |
            |                     +-- isolates the store: a directory, or a Redis key prefix
            v
  DiskCacheService  or  RedisCacheService            (both are CacheService)
            |
            v
  registry.add_cache(name, cache, namespace=...)     keyed on (agent, name)
            |
            v
  self.registry.get_cache("sessions")  in any component of that agent
```

Two design points worth knowing:

- **The factory isolates the store, not the caller.** How a backend separates two caches is
  knowledge only that backend has -- the disk cache separates by directory, Redis by key prefix --
  so a new backend answers that question in the method that creates it, and no caller has to.
- **`key_prefix` and `namespace` are different tools.** `key_prefix` is configured once per
  deployment and keeps whole services apart in a shared Redis. `namespace` is passed per call and
  organises one cache's own keys. Both appear in every Redis key.

A new backend means implementing `CacheService` and extending the factory. Nothing that uses a
cache has to change.

---

## Where things live

| Path | What |
|---|---|
| `services/infrastructure/cache_service.py` | `CacheService` (the interface) and `DiskCacheService` |
| `services/infrastructure/redis_cache_service.py` | `RedisCacheService` |
| `services/infrastructure/cache_backend_factory.py` | Backend selection and store isolation |
| `io/api/utilities/cache.py` | The management API |
| `io/api/actuators/health/cache_health.py` | The readiness check |
| `models/config.py` | `CacheConfig` |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError: Redis backend requires ...[redis]` | The extra is not installed | `pip install 'avs-blueprint-agents[redis]'` |
| Logs show `DiskCacheService` with `backend = "redis"` set | The settings file is not the one being read, or the section is misspelt | Confirm `[default.cache]` and the `settings_files` path |
| `No cache registered as 'sessions'` | That agent never declared it | Add `.with_cache(name="sessions")`; there is no fallback to the default |
| Two replicas do not see each other's writes | Different `key_prefix` or `redis_url` | They must match exactly for replicas of one service |
| Two services overwrite each other's keys | The same `key_prefix` for different services | Give each service its own |
| An agent cannot see a cache its neighbour declared | Working as designed | Declare one in that agent too |
| `/api/cache/stats` answers 503 | The application built no cache | `with_cache()` |
| Entries vanished after an upgrade | The per-agent key layout changed | Expected once; the cache refills |
