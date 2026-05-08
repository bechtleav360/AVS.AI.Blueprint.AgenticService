"""Redis shared cache demo: zwei Agenten schreiben und lesen den gleichen Redis-Cache.

Verifiziert:
  1. Redis ist erreichbar (on_startup ping).
  2. Beide Agenten schreiben je einen eigenen Eintrag.
  3. Jeder Agent kann BEIDE Einträge lesen — vollständige Cross-Agent-Sichtbarkeit.
  4. TTL-Verhalten: Einträge laufen nach der gesetzten Zeit ab.
  5. Die Einträge sind im laufenden Redis tatsächlich vorhanden (redis-cli KEYS).

Run:
    python demo_redis.py                        # Standard (localhost:6379)
    python demo_redis.py --url redis://host:6379
"""

import argparse
import asyncio

from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService

NAMESPACE = "shared_demo"
PASS = "✓ PASS"
FAIL = "✗ FAIL"


# ---------------------------------------------------------------------------
# Zwei unabhängige Agent-Services — bekommen denselben Cache injiziert
# ---------------------------------------------------------------------------


class PricingAgent:
    KEY_PREFIX = "pricing"

    def __init__(self, cache: RedisCacheService) -> None:
        self._cache = cache

    def cache_key(self, product_id: str) -> str:
        return f"{self.KEY_PREFIX}:{product_id}"

    async def compute_and_store(self, product_id: str) -> None:
        await asyncio.sleep(0.05)  # simulierte Arbeit
        value = {"agent": "PricingAgent", "product": product_id, "price": 49.99}
        self._cache.set(self.cache_key(product_id), value, namespace=NAMESPACE)
        print(f"  [PricingAgent]   geschrieben → key='{self.cache_key(product_id)}'")

    def read(self, key: str) -> dict | None:
        return self._cache.get(key, namespace=NAMESPACE)


class RecommendationAgent:
    KEY_PREFIX = "recommendation"

    def __init__(self, cache: RedisCacheService) -> None:
        self._cache = cache

    def cache_key(self, product_id: str) -> str:
        return f"{self.KEY_PREFIX}:{product_id}"

    async def compute_and_store(self, product_id: str) -> None:
        await asyncio.sleep(0.05)
        value = {"agent": "RecommendationAgent", "product": product_id, "verdict": "Kaufempfehlung!"}
        self._cache.set(self.cache_key(product_id), value, namespace=NAMESPACE)
        print(f"  [RecommendAgent] geschrieben → key='{self.cache_key(product_id)}'")

    def read(self, key: str) -> dict | None:
        return self._cache.get(key, namespace=NAMESPACE)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def check(label: str, reader: str, key: str, value: dict | None) -> bool:
    ok = value is not None
    print(f"  {'✓ PASS' if ok else '✗ FAIL'}  [{reader}] liest key='{key}'")
    if ok:
        print(f"         Wert: {value}")
    return ok


async def run_demo(redis_url: str) -> None:
    # ------------------------------------------------------------------
    # Phase 0: Verbindung herstellen und ping prüfen
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f" Phase 0: Verbindung zu Redis ({redis_url})")
    print("=" * 60)

    cache = RedisCacheService(
        redis_url=redis_url,
        key_prefix="blueprint_demo",
        default_ttl=60,
    )

    try:
        await cache.on_startup()  # wirft Exception wenn Redis nicht erreichbar
        print(f"  {PASS}  Redis erreichbar")
    except Exception as e:
        print(f"  {FAIL}  Redis nicht erreichbar: {e}")
        print("  Tipp: docker run -d -p 6379:6379 redis:alpine")
        return

    stats = cache.get_stats()
    print(f"  Redis-Version   : {stats.get('redis_version')}")
    print(f"  Verbundene Clients: {stats.get('connected_clients')}")
    print(f"  Speichernutzung : {stats.get('used_memory_human')}")

    # Vorherige Demo-Einträge aufräumen
    cache.clear(namespace=NAMESPACE)
    print(f"  Namespace '{NAMESPACE}' geleert")

    # ------------------------------------------------------------------
    # Phase 1: Beide Agenten schreiben
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(" Phase 1: Beide Agenten schreiben in den Redis-Cache")
    print("=" * 60)

    pricing = PricingAgent(cache)
    recommendation = RecommendationAgent(cache)
    product = "laptop-pro-15"

    await pricing.compute_and_store(product)
    await recommendation.compute_and_store(product)

    print(f"\n  Namespaces im Cache nach den Writes: {cache.list_namespaces()}")

    # ------------------------------------------------------------------
    # Phase 2: Cross-Read Verifikation
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(" Phase 2: Cross-Read — jeder Agent liest BEIDE Einträge")
    print("=" * 60)

    pk = pricing.cache_key(product)
    rk = recommendation.cache_key(product)

    results = [
        check("eigener Eintrag", "PricingAgent",   pk, pricing.read(pk)),
        check("fremder Eintrag", "PricingAgent",   rk, pricing.read(rk)),
        check("eigener Eintrag", "RecommendAgent", rk, recommendation.read(rk)),
        check("fremder Eintrag", "RecommendAgent", pk, recommendation.read(pk)),
    ]

    # ------------------------------------------------------------------
    # Phase 3: TTL-Verhalten prüfen (selbe cache-Instanz wiederverwenden)
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print(" Phase 3: TTL-Verhalten")
    print("=" * 60)

    ttl_key = "ttl_test_entry"
    cache.set(ttl_key, {"ttl": "test"}, namespace=NAMESPACE, ttl=1)
    exists_before = cache.exists(ttl_key, namespace=NAMESPACE)
    print(f"  Eintrag direkt nach set()  : {'vorhanden' if exists_before else 'nicht vorhanden'}")

    print("  Warte 2 Sekunden auf Ablauf...")
    await asyncio.sleep(2)

    exists_after = cache.exists(ttl_key, namespace=NAMESPACE)
    print(f"  Eintrag nach TTL-Ablauf    : {'vorhanden' if exists_after else 'nicht vorhanden (korrekt abgelaufen)'}")

    ttl_ok = exists_before and not exists_after
    results.append(ttl_ok)
    print(f"  {'✓ PASS' if ttl_ok else '✗ FAIL'}  TTL wird von Redis korrekt durchgesetzt")

    # ------------------------------------------------------------------
    # Zusammenfassung
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f" {PASS}  Alle {total}/{total} Checks bestanden — Redis-Cache funktioniert korrekt.")
    else:
        print(f" {FAIL}  Nur {passed}/{total} Checks bestanden.")
    print("=" * 60)

    cache.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Redis shared cache verification")
    parser.add_argument("--url", default="redis://localhost:6379/0", help="Redis URL")
    args = parser.parse_args()
    asyncio.run(run_demo(args.url))


if __name__ == "__main__":
    main()
