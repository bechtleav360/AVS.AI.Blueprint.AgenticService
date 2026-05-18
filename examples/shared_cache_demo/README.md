# Shared Cache Demo

These scripts verify that the blueprint's centralized Redis cache works correctly, including across separate OS-level processes (i.e., separate service replicas).

## Prerequisites

**1. Install the package** (from the project root):
```bash
pip install -e ".[redis]"
```

**2. Start Redis** (Docker is the easiest option):
```bash
docker run -d -p 6379:6379 redis:alpine
```

---

## Scripts

### `walkthrough.py` — Step-by-step demo for live presentations *(recommended)*

A narrated, end-to-end tour that maps each acceptance criterion from the issue to a runnable demonstration. Use `--pause` for live demos so you can talk through each step.

```bash
python walkthrough.py            # auto-advance, ~15 seconds
python walkthrough.py --pause    # waits for <Enter> between steps
python walkthrough.py --no-redis # only run DiskCache steps (no Redis needed)
```

Steps and the acceptance criteria they cover:

| # | Title | AC |
|---|---|---|
| 1 | The unified Cache interface | AC-01 |
| 2 | DiskCache: basic CRUD | AC-03 |
| 3 | TTL expiry on DiskCache | AC-04 |
| 4 | Namespaces isolate keys | AC-06 |
| 5 | Switching backends via `CacheConfig` | AC-02 |
| 6 | Redis: TTL is identical | AC-04 |
| 7 | `key_prefix` isolates services | AC-06 |
| 8 | Cross-process sharing (calls `demo_multiprocess.py`) | AC-01, AC-02 |
| 9 | Fallback when Redis is unreachable | AC-05 |

The script ends with a summary table that ticks off every acceptance criterion.

---

### `demo.py` — DiskCache, single process

Verifies that two agent objects sharing a single `DiskCacheService` instance can read each other's entries. Useful as a baseline; no Redis required.

```bash
python demo.py           # run with existing cache
python demo.py --clear   # wipe cache first
```

**What it proves:** The DiskCache backend and the shared-cache pattern work correctly within one process.

---

### `demo_redis.py` — Redis, single process

Same as above but using `RedisCacheService`. Both agents share one Redis connection object.

```bash
python demo_redis.py
python demo_redis.py --url redis://host:6379
```

**What it proves:** The Redis backend serialises, stores, and retrieves values correctly, and TTL expiry works.

---

### `demo_multiprocess.py` — Redis, two separate processes

The definitive cross-instance test. Two worker processes are spawned as independent OS-level processes. Each creates its **own** `RedisCacheService` with its own TCP connection to Redis — no shared Python objects. Worker B reads a value that Worker A wrote.

```bash
python demo_multiprocess.py
python demo_multiprocess.py --url redis://host:6379
python demo_multiprocess.py --clear   # wipe namespace first
```

Expected output (all checks green):
```
============================...
 Phase 0: Redis connectivity (redis://localhost:6379/0)
============================...
  ✓ PASS  Redis is reachable

============================...
 Phase 1: Two separate processes share the same Redis cache
  Main PID: 12345
============================...
  [Replica-A | pid=12346]  wrote  → key='service_a_result'  ...
  [Replica-B | pid=12347]  read   → key='service_a_result'  ...
  [Replica-B | pid=12347]  wrote  → key='service_b_result'  ...

============================...
 Summary
============================...
  ✓ PASS  Replica-B reads Replica-A's key (cross-process read)
  ✓ PASS  Replica-B reads its own key
  ✓ PASS  Main process reads Replica-A's key
  ✓ PASS  Main process reads Replica-B's key

  ✓ PASS  All 4/4 checks passed — cross-instance cache sharing works.
```

**What it proves:** Multiple independent service instances (different PIDs, different `RedisCacheService` objects) share cache state through Redis. This is the core guarantee of the centralized cache feature.
