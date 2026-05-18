"""Shared cache demo: two agents writing to and reading from the same cache.

Verification steps:
  1. Both agents write their own entry into the shared cache.
  2. Both agents then read BOTH entries — proving full cross-agent visibility.

Run:
    python demo.py           # run with existing cache
    python demo.py --clear   # wipe cache first (cold-start path)
"""

import argparse
import asyncio
import shutil
from pathlib import Path

from blueprint.agents.services.infrastructure.cache_service import DiskCacheService

SHARED_CACHE_DIR = ".cache/shared_demo"
NAMESPACE = "results"

PASS = "✓ PASS"
FAIL = "✗ FAIL"


# ---------------------------------------------------------------------------
# Two independent agent services — each gets the same cache injected
# ---------------------------------------------------------------------------


class PricingAgent:
    """Computes a product price and stores it under key 'pricing:<product_id>'."""

    KEY_PREFIX = "pricing"

    def __init__(self, cache: DiskCacheService) -> None:
        self._cache = cache

    def cache_key(self, product_id: str) -> str:
        return f"{self.KEY_PREFIX}:{product_id}"

    async def compute_and_store(self, product_id: str) -> None:
        await asyncio.sleep(0.1)  # simulate work
        value = f"price=49.99 EUR (computed by PricingAgent for '{product_id}')"
        self._cache.set(self.cache_key(product_id), value, namespace=NAMESPACE)
        print(f"  [PricingAgent]      wrote  → key='{self.cache_key(product_id)}'")

    def read(self, key: str) -> str | None:
        return self._cache.get(key, namespace=NAMESPACE)


class RecommendationAgent:
    """Computes a recommendation and stores it under key 'recommendation:<product_id>'."""

    KEY_PREFIX = "recommendation"

    def __init__(self, cache: DiskCacheService) -> None:
        self._cache = cache

    def cache_key(self, product_id: str) -> str:
        return f"{self.KEY_PREFIX}:{product_id}"

    async def compute_and_store(self, product_id: str) -> None:
        await asyncio.sleep(0.1)  # simulate work
        value = f"recommendation='Buy it!' (computed by RecommendationAgent for '{product_id}')"
        self._cache.set(self.cache_key(product_id), value, namespace=NAMESPACE)
        print(f"  [RecommendAgent]    wrote  → key='{self.cache_key(product_id)}'")

    def read(self, key: str) -> str | None:
        return self._cache.get(key, namespace=NAMESPACE)


# ---------------------------------------------------------------------------
# Verification helper
# ---------------------------------------------------------------------------


def verify(label: str, agent_name: str, key: str, value: str | None) -> bool:
    status = PASS if value is not None else FAIL
    print(f"  {status}  [{agent_name}] reads key='{key}'")
    if value is not None:
        print(f"         value='{value}'")
    return value is not None


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------


async def run_demo() -> None:
    shared_cache = DiskCacheService(cache_dir=SHARED_CACHE_DIR)

    pricing = PricingAgent(shared_cache)
    recommendation = RecommendationAgent(shared_cache)

    product = "laptop-pro-15"

    # ------------------------------------------------------------------
    # Phase 1: Both agents write their own entry
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(" Phase 1: Both agents compute and write to the shared cache")
    print("=" * 60)
    await pricing.compute_and_store(product)
    await recommendation.compute_and_store(product)
    print(f"\n  Cache size after writes: {shared_cache.get_stats()['size']} entries")

    # ------------------------------------------------------------------
    # Phase 2: Cross-read verification
    # Each agent reads BOTH entries — its own and the other agent's.
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(" Phase 2: Cross-read verification")
    print(" Each agent must be able to read BOTH entries")
    print("=" * 60)

    pricing_key = pricing.cache_key(product)
    recommendation_key = recommendation.cache_key(product)

    results = [
        verify("own entry",   "PricingAgent",   pricing_key,        pricing.read(pricing_key)),
        verify("other entry", "PricingAgent",   recommendation_key, pricing.read(recommendation_key)),
        verify("own entry",   "RecommendAgent", recommendation_key, recommendation.read(recommendation_key)),
        verify("other entry", "RecommendAgent", pricing_key,        recommendation.read(pricing_key)),
    ]

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f" {PASS}  All {total}/{total} cross-read checks passed — shared cache works correctly.")
    else:
        print(f" {FAIL}  Only {passed}/{total} checks passed.")
    print("=" * 60)

    shared_cache.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Shared cache cross-read verification")
    parser.add_argument("--clear", action="store_true", help="Clear the cache before running")
    args = parser.parse_args()

    if args.clear and Path(SHARED_CACHE_DIR).exists():
        shutil.rmtree(SHARED_CACHE_DIR)
        print(f"Cache cleared: {SHARED_CACHE_DIR}")

    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
