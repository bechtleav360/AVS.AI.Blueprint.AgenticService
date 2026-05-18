"""Multi-process shared-cache demo with two independently built agents.

Two agent classes (PricingAgent, RecommendationAgent) are each constructed
inside their own OS-level process. Each agent builds its OWN RedisCacheService
instance — different PIDs, different Python objects, different TCP sockets to
Redis. They collaborate purely through the shared Redis cache:

    Process A (pid=X)                  Redis                 Process B (pid=Y)
    ┌──────────────────┐                                     ┌─────────────────────┐
    │ PricingAgent     │                                     │ RecommendationAgent │
    │   compute_price  │ ──── set price:laptop ─────────►    │                     │
    │                  │                                     │   read price:laptop │
    │                  │ ◄──── get recommendation:laptop ─── │   compute_verdict   │
    │   read verdict   │                                     │   set verdict       │
    └──────────────────┘                                     └─────────────────────┘

If Process B can read the price that Process A wrote (and vice versa for the
recommendation), the centralized cache works across instances.

Run:
    python demo_multiprocess.py
    python demo_multiprocess.py --url redis://host:6379
    python demo_multiprocess.py --clear
"""

import argparse
import multiprocessing
import os
import sys
import time
from typing import Any

from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService

NAMESPACE = "shared_demo"
KEY_PREFIX = "blueprint_mp_demo"
PRODUCT_ID = "laptop-pro-15"

PASS = "✓ PASS"
FAIL = "✗ FAIL"


# ---------------------------------------------------------------------------
# Agent classes — each agent owns its OWN RedisCacheService instance
# ---------------------------------------------------------------------------


class PricingAgent:
    """Computes prices and publishes them to the shared cache.

    Each PricingAgent instance builds its own RedisCacheService — there is no
    shared Python object across processes. The only shared state is Redis.
    """

    def __init__(self, redis_url: str) -> None:
        self._pid = os.getpid()
        self._cache = RedisCacheService(redis_url=redis_url, key_prefix=KEY_PREFIX)
        print(
            f"    [PricingAgent       pid={self._pid}] "
            f"built — own RedisCacheService @ {redis_url}",
            flush=True,
        )

    def compute_and_publish_price(self, product_id: str) -> dict[str, Any]:
        time.sleep(0.05)  # simulate work
        price = {
            "product": product_id,
            "amount": 49.99,
            "currency": "EUR",
            "computed_by_pid": self._pid,
        }
        key = f"price:{product_id}"
        print(
            f"    [PricingAgent       pid={self._pid}] "
            f"computed price → {price}",
            flush=True,
        )
        self._cache.set(key, price, namespace=NAMESPACE)
        print(
            f"    [PricingAgent       pid={self._pid}] "
            f"WROTE  Redis key='{NAMESPACE}:{key}'",
            flush=True,
        )
        return price

    def read_recommendation(self, product_id: str) -> dict[str, Any] | None:
        key = f"recommendation:{product_id}"
        value = self._cache.get(key, namespace=NAMESPACE)
        if value is not None:
            print(
                f"    [PricingAgent       pid={self._pid}] "
                f"READ   Redis key='{NAMESPACE}:{key}' → {value}",
                flush=True,
            )
        else:
            print(
                f"    [PricingAgent       pid={self._pid}] "
                f"READ   Redis key='{NAMESPACE}:{key}' → MISS",
                flush=True,
            )
        return value

    def close(self) -> None:
        self._cache.close()


class RecommendationAgent:
    """Reads the price published by PricingAgent and emits a buy/wait verdict."""

    def __init__(self, redis_url: str) -> None:
        self._pid = os.getpid()
        self._cache = RedisCacheService(redis_url=redis_url, key_prefix=KEY_PREFIX)
        print(
            f"    [RecommendationAgent pid={self._pid}] "
            f"built — own RedisCacheService @ {redis_url}",
            flush=True,
        )

    def read_price(self, product_id: str) -> dict[str, Any] | None:
        key = f"price:{product_id}"
        value = self._cache.get(key, namespace=NAMESPACE)
        if value is not None:
            print(
                f"    [RecommendationAgent pid={self._pid}] "
                f"READ   Redis key='{NAMESPACE}:{key}' → {value}",
                flush=True,
            )
        else:
            print(
                f"    [RecommendationAgent pid={self._pid}] "
                f"READ   Redis key='{NAMESPACE}:{key}' → MISS",
                flush=True,
            )
        return value

    def compute_and_publish_recommendation(
        self, product_id: str, price: dict[str, Any]
    ) -> dict[str, Any]:
        time.sleep(0.05)
        verdict = "BUY" if price["amount"] < 100 else "WAIT"
        recommendation = {
            "product": product_id,
            "verdict": verdict,
            "based_on_price": price["amount"],
            "computed_by_pid": self._pid,
        }
        key = f"recommendation:{product_id}"
        print(
            f"    [RecommendationAgent pid={self._pid}] "
            f"computed → {recommendation}",
            flush=True,
        )
        self._cache.set(key, recommendation, namespace=NAMESPACE)
        print(
            f"    [RecommendationAgent pid={self._pid}] "
            f"WROTE  Redis key='{NAMESPACE}:{key}'",
            flush=True,
        )
        return recommendation

    def close(self) -> None:
        self._cache.close()


# ---------------------------------------------------------------------------
# Process entry points — each runs in a separate OS-level process
# ---------------------------------------------------------------------------


def process_a(
    redis_url: str,
    price_ready: "multiprocessing.Event",
    recommendation_ready: "multiprocessing.Event",
    result_queue: "multiprocessing.Queue",
) -> None:
    """Process A: builds PricingAgent, publishes price, then reads RecommendationAgent's verdict."""
    print(f"\n  ─── Process A starting (pid={os.getpid()}) ───", flush=True)
    agent = PricingAgent(redis_url)

    # Step 1: compute and publish price
    print(f"\n  ─── Process A step 1: publish price ───", flush=True)
    agent.compute_and_publish_price(PRODUCT_ID)

    # Signal Process B: the price is now in Redis
    price_ready.set()
    print(f"\n  ─── Process A signalled 'price_ready' — waiting for Process B ───", flush=True)

    # Step 2: wait for B to publish a recommendation, then read it
    recommendation_ready.wait(timeout=10)
    print(f"\n  ─── Process A step 2: read recommendation written by Process B ───", flush=True)
    verdict = agent.read_recommendation(PRODUCT_ID)

    result_queue.put(
        {
            "process": "A",
            "pid": os.getpid(),
            "could_read_other_processes_write": verdict is not None,
            "value_seen": verdict,
        }
    )
    agent.close()


def process_b(
    redis_url: str,
    price_ready: "multiprocessing.Event",
    recommendation_ready: "multiprocessing.Event",
    result_queue: "multiprocessing.Queue",
) -> None:
    """Process B: builds RecommendationAgent, reads price, publishes recommendation."""
    price_ready.wait(timeout=10)  # wait until Process A has written the price

    print(f"\n  ─── Process B starting (pid={os.getpid()}) ───", flush=True)
    agent = RecommendationAgent(redis_url)

    # Step 1: read price written by PricingAgent in Process A — the cross-process read
    print(f"\n  ─── Process B step 1: read price written by Process A ───", flush=True)
    price = agent.read_price(PRODUCT_ID)

    if price is None:
        result_queue.put(
            {
                "process": "B",
                "pid": os.getpid(),
                "could_read_other_processes_write": False,
                "value_seen": None,
            }
        )
        recommendation_ready.set()
        agent.close()
        return

    # Step 2: compute and publish a recommendation based on that price
    print(f"\n  ─── Process B step 2: publish recommendation ───", flush=True)
    agent.compute_and_publish_recommendation(PRODUCT_ID, price)

    result_queue.put(
        {
            "process": "B",
            "pid": os.getpid(),
            "could_read_other_processes_write": True,
            "value_seen": price,
        }
    )
    recommendation_ready.set()
    agent.close()


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------


def run_demo(redis_url: str, clear: bool) -> None:
    # ---- Phase 0: Redis connectivity ---------------------------------------
    # The main process keeps ONE RedisCacheService instance across phases
    # because Component registers itself by class name and rejects duplicates
    # within the same process. (Each child process has its own registry.)
    print("\n" + "=" * 70)
    print(f" Phase 0: Redis connectivity check ({redis_url})")
    print("=" * 70)
    main_cache = RedisCacheService(redis_url=redis_url, key_prefix=KEY_PREFIX)
    try:
        main_cache._client.ping()
        print(f"  {PASS}  Redis is reachable", flush=True)
    except Exception as exc:
        print(f"  {FAIL}  Cannot reach Redis: {exc}")
        print("  Tip: docker run -d -p 6379:6379 redis:alpine")
        sys.exit(1)

    if clear:
        main_cache.clear(namespace=NAMESPACE)
        print(f"  Namespace '{NAMESPACE}' cleared")

    # ---- Phase 1: spawn two processes, each builds its own agent ----------
    print("\n" + "=" * 70)
    print(" Phase 1: Spawn two OS-level processes — each builds its own agent")
    print(f"  Main process pid = {os.getpid()}")
    print("=" * 70)

    price_ready: multiprocessing.Event = multiprocessing.Event()
    recommendation_ready: multiprocessing.Event = multiprocessing.Event()
    result_queue: multiprocessing.Queue = multiprocessing.Queue()

    proc_a = multiprocessing.Process(
        target=process_a,
        args=(redis_url, price_ready, recommendation_ready, result_queue),
        name="ProcessA-PricingAgent",
    )
    proc_b = multiprocessing.Process(
        target=process_b,
        args=(redis_url, price_ready, recommendation_ready, result_queue),
        name="ProcessB-RecommendationAgent",
    )

    proc_a.start()
    proc_b.start()
    proc_a.join(timeout=15)
    proc_b.join(timeout=15)

    results = []
    while not result_queue.empty():
        results.append(result_queue.get())
    results_by_process = {r["process"]: r for r in results}

    # ---- Phase 2: independent main-process reader ------------------------
    print("\n" + "=" * 70)
    print(" Phase 2: Main process — a 3rd independent reader")
    print("=" * 70)

    main_price = main_cache.get(f"price:{PRODUCT_ID}", namespace=NAMESPACE)
    main_recommendation = main_cache.get(f"recommendation:{PRODUCT_ID}", namespace=NAMESPACE)
    print(f"  Main reads price          : {main_price}")
    print(f"  Main reads recommendation : {main_recommendation}")
    print(f"  Namespaces in Redis       : {main_cache.list_namespaces()}")
    main_cache.close()

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 70)
    print(" Summary — cross-instance cache visibility")
    print("=" * 70)

    res_b = results_by_process.get("B", {})
    res_a = results_by_process.get("A", {})

    checks = [
        (
            "RecommendationAgent (Process B) reads price written by PricingAgent (Process A)",
            res_b.get("could_read_other_processes_write", False),
        ),
        (
            "PricingAgent (Process A) reads recommendation written by Process B",
            res_a.get("could_read_other_processes_write", False),
        ),
        ("Main process reads the price",          main_price is not None),
        ("Main process reads the recommendation", main_recommendation is not None),
    ]

    for label, ok in checks:
        print(f"  {'✓ PASS' if ok else '✗ FAIL'}  {label}")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print()
    if passed == total:
        print(f"  {PASS}  All {total}/{total} checks passed — agents share cache across processes.")
    else:
        print(f"  {FAIL}  {passed}/{total} checks passed.")
    print("=" * 70 + "\n")

    sys.exit(0 if passed == total else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-process Redis cache sharing demo")
    parser.add_argument("--url", default="redis://localhost:6379/0", help="Redis URL")
    parser.add_argument("--clear", action="store_true", help="Clear namespace before running")
    args = parser.parse_args()

    # 'spawn' makes the demo behave consistently on Linux, macOS, and Windows
    # (forces fresh module import in each child process — matches real replicas).
    multiprocessing.set_start_method("spawn", force=True)

    run_demo(args.url, args.clear)


if __name__ == "__main__":
    main()
