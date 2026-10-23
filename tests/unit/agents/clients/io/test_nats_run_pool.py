"""Run limits: one guaranteed run per (agent, connection), the rest from a process pool (plan D7, step 3b)."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from blueprint.agents.clients.io.nats_client import NATSClient
from blueprint.agents.clients.io.nats_run_pool import PairRuns, RunLimit, RunPool
from blueprint.agents.models.events import CloudEvent
from tests.unit.agents.clients.io.test_nats_connection_source import FakeSource, _binding, _bound_handler, _delivery, _subscribed


class TestRunLimit:
    @pytest.mark.parametrize("raw", [None, ""])
    def test_unset(self, raw: object) -> None:
        assert RunLimit.parse("k", raw, minimum=1) is None

    @pytest.mark.parametrize("raw", [4, "4", " 4 "])
    def test_a_number(self, raw: object) -> None:
        assert RunLimit.parse("k", raw, minimum=1) == RunLimit(absolute=4, minimum=1)

    def test_a_percentage_of_the_pairs(self) -> None:
        limit = RunLimit.parse("k", "33%", minimum=1)
        assert limit is not None
        assert limit.resolve(300) == 99
        assert limit.resolve(6) == 2
        assert limit.resolve(0) == 1, "never below the minimum"

    @pytest.mark.parametrize("raw", ["x", "0%", "101%", "%", True, 0, -1], ids=["text", "0%", "101%", "bare-%", "bool", "zero", "negative"])
    def test_anything_else_is_refused_naming_the_key(self, raw: object) -> None:
        with pytest.raises(ValueError, match="nats_max_concurrent_runs"):
            RunLimit.parse("nats_max_concurrent_runs", raw, minimum=1)

    def test_the_pool_may_be_zero(self) -> None:
        assert RunLimit.parse("nats_extra_runs_per_process", 0, minimum=0) == RunLimit(absolute=0, minimum=0)


class TestRunPool:
    async def test_the_guaranteed_run_needs_no_pool(self) -> None:
        pool = RunPool(RunLimit(absolute=0))
        pool.add_pair()
        release = await pool.acquire(PairRuns(), RunLimit(absolute=5, minimum=1))
        assert pool.extras_running == 0
        release()

    async def test_further_runs_need_both_the_pairs_limit_and_the_pool(self) -> None:
        pool = RunPool(RunLimit(absolute=1))
        busy, idle = PairRuns(), PairRuns()
        pool.add_pair()
        pool.add_pair()
        k = RunLimit(absolute=3, minimum=1)

        first = await pool.acquire(busy, k)  # guaranteed
        second = await pool.acquire(busy, k)  # the one pool slot
        third = asyncio.create_task(pool.acquire(busy, k))
        await asyncio.sleep(0)
        assert not third.done(), "the pool is exhausted"

        idle_first = await pool.acquire(idle, k)  # an idle pair never waits for the pool
        assert idle.guaranteed_busy

        second()  # the pool slot comes back
        await asyncio.sleep(0)
        assert third.done()
        assert busy.running == 2
        for release in (first, third.result(), idle_first):
            release()
        assert pool.extras_running == 0 and busy.running == 0

    async def test_a_pair_never_exceeds_its_limit(self) -> None:
        pool = RunPool(None)
        pair, k = PairRuns(), RunLimit(absolute=2, minimum=1)
        pool.add_pair()
        await pool.acquire(pair, k)
        await pool.acquire(pair, k)
        waiting = asyncio.create_task(pool.acquire(pair, k))
        await asyncio.sleep(0)
        assert not waiting.done()
        waiting.cancel()

    async def test_waiters_are_served_in_arrival_order(self) -> None:
        pool = RunPool(RunLimit(absolute=1))
        a, b = PairRuns(), PairRuns()
        for _ in range(2):
            pool.add_pair()
        k = RunLimit(absolute=5, minimum=1)
        await pool.acquire(a, k)
        await pool.acquire(b, k)
        holder = await pool.acquire(a, k)
        order: list[str] = []

        async def wait(name: str, pair: PairRuns) -> None:
            (await pool.acquire(pair, k))()
            order.append(name)

        tasks = [asyncio.create_task(wait("b", b)), asyncio.create_task(wait("a", a))]
        await asyncio.sleep(0)
        holder()
        await asyncio.gather(*tasks)
        assert order == ["b", "a"]

    async def test_a_cancelled_waiter_leaves_nothing_behind(self) -> None:
        pool = RunPool(RunLimit(absolute=0))
        pair, k = PairRuns(), RunLimit(absolute=5, minimum=1)
        pool.add_pair()
        guaranteed = await pool.acquire(pair, k)
        waiting = asyncio.create_task(pool.acquire(pair, k))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        guaranteed()
        assert pair.running == 0 and not pair.guaranteed_busy

    async def test_a_percentage_follows_the_pairs(self) -> None:
        """Resolved at every request: a pair added later raises the pool, and a waiter is woken by it."""
        pool = RunPool(RunLimit(percent=50))
        pair, k = PairRuns(), RunLimit(absolute=10, minimum=1)
        await pool.acquire(pair, k)  # guaranteed
        waiting = asyncio.create_task(pool.acquire(pair, k))
        await asyncio.sleep(0)
        assert not waiting.done(), "50% of no pairs is no pool slot"
        pool.add_pair()  # 50% of 1 pair rounds up to 1
        await asyncio.sleep(0)
        assert waiting.done()


class TestTheClientUsesThePool:
    async def test_an_idle_connection_runs_while_a_busy_one_has_exhausted_the_pool(
        self, nats_client: NATSClient, mock_config: MagicMock, mock_nats_core: MagicMock, cloud_event: CloudEvent
    ) -> None:
        base = mock_config.get.side_effect
        mock_config.get.side_effect = lambda key, default=None: 3 if key == "nats_max_concurrent_runs" else base(key, default)
        nats_client.set_run_pool(RunPool(RunLimit(absolute=1)))
        gate = asyncio.Event()
        started: list[str] = []

        async def callback(event: Any, subject: str) -> None:
            started.append(subject)
            await gate.wait()

        await _subscribed(nats_client, FakeSource({"A": _binding("A", "risk.>"), "B": _binding("B", "risk.>")}), ("risk.>",))
        for binding in nats_client._named:
            binding.topic_callbacks["risk.>"] = callback
        a, handler_a = await _bound_handler(nats_client, mock_nats_core, "A")
        b, handler_b = await _bound_handler(nats_client, mock_nats_core, "B")

        callers = [asyncio.create_task(handler_a(_delivery(cloud_event, "t.A.risk.created"))) for _ in range(3)]
        for _ in range(20):
            await asyncio.sleep(0)
        assert len(started) == 2, "A: its guaranteed run plus the one pool slot; the third waits"
        await handler_b(_delivery(cloud_event, "t.B.risk.created"))
        for _ in range(20):
            await asyncio.sleep(0)
        assert len(started) == 3, "B's guaranteed run starts although the pool is exhausted"

        gate.set()
        await asyncio.gather(*callers)
        await asyncio.gather(*list(a.runs), *list(b.runs))
        assert len(started) == 4
