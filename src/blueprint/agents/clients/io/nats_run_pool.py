"""How many deliveries run at once: one guaranteed per (agent, connection), the rest from a process pool.

Named-connections plan, decision D7. Event rates differ by orders of magnitude between agents -- once
an hour for one, several times a minute for another -- so a busy pair may take many runs while an
idle one must never wait:

- **One run per (agent, connection) is always allowed** and counts against no limit.
- **Every further run** needs both: its pair is below ``nats_max_concurrent_runs`` (K), and a slot
  of the process-wide pool ``nats_extra_runs_per_process`` is free.

Both limits take an absolute number or a percentage of the pairs the process currently consumes on
(``"33%"``), resolved at every request, so they follow pairs being added or removed. Waiters are
served first come, first served among those that may run, so no pair starves another.
"""

import asyncio
import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

Release = Callable[[], None]


@dataclass(frozen=True)
class RunLimit:
    """A configured amount: ``absolute`` runs, or ``percent`` of the process's pairs (at least ``minimum``)."""

    absolute: int | None = None
    percent: float | None = None
    minimum: int = 0

    @classmethod
    def parse(cls, key: str, raw: object, *, minimum: int) -> "RunLimit | None":
        """Read ``raw`` as a number or ``"N%"``; ``None`` when it is unset.

        Raises:
            ValueError: anything else, a number below ``minimum``, or a percentage outside
                (0, 100]. The message names the key.
        """
        if raw is None or raw == "":
            return None
        if isinstance(raw, bool):
            raise ValueError(f"'{key}' must be a number or a percentage such as \"33%\", got {raw!r}.")
        if isinstance(raw, int):
            return cls._absolute(key, raw, minimum)
        text = str(raw).strip()
        if text.endswith("%"):
            try:
                percent = float(text[:-1])
            except ValueError:
                raise ValueError(f"'{key}' is {raw!r}, which is not a percentage such as \"33%\".") from None
            if not 0 < percent <= 100:
                raise ValueError(f"'{key}' must be a percentage above 0 and at most 100, got {raw!r}.")
            return cls(percent=percent, minimum=minimum)
        try:
            return cls._absolute(key, int(text), minimum)
        except ValueError as exc:
            if "must be" in str(exc):
                raise
            raise ValueError(f"'{key}' must be a number or a percentage such as \"33%\", got {raw!r}.") from None

    @classmethod
    def _absolute(cls, key: str, value: int, minimum: int) -> "RunLimit":
        if value < minimum:
            raise ValueError(f"'{key}' must be at least {minimum}, got {value}.")
        return cls(absolute=value, minimum=minimum)

    def resolve(self, pairs: int) -> int:
        """The amount for a process that currently consumes on ``pairs`` (agent, connection) pairs."""
        if self.absolute is not None:
            return self.absolute
        return max(self.minimum, math.ceil(pairs * (self.percent or 0) / 100))


@dataclass
class PairRuns:
    """What one (agent, connection) pair has running: its guaranteed run, and how many in total."""

    guaranteed_busy: bool = False
    running: int = 0


class RunPool:
    """The process-wide pool of runs beyond each pair's guaranteed one. One per process, shared by every client."""

    def __init__(self, extra: RunLimit | None = None) -> None:
        self._extra = extra
        self._extras_running = 0
        self._pairs = 0
        self._waiters: deque[tuple[PairRuns, RunLimit, asyncio.Future[Release]]] = deque()

    @property
    def pairs(self) -> int:
        """The (agent, connection) pairs the process consumes on, which percentages are taken of."""
        return self._pairs

    @property
    def extras_running(self) -> int:
        """Runs currently holding a slot of the pool."""
        return self._extras_running

    def add_pair(self) -> None:
        self._pairs += 1
        self._wake()

    def remove_pair(self) -> None:
        self._pairs = max(0, self._pairs - 1)

    async def acquire(self, pair: PairRuns, limit: RunLimit) -> Release:
        """Wait until ``pair`` may start a run; return what frees it again.

        The pair's guaranteed run is granted at once whenever it is free; a further run waits for
        both the pair's limit and the pool.
        """
        granted = self._try(pair, limit)
        if granted is not None:
            return granted
        waiter: asyncio.Future[Release] = asyncio.get_running_loop().create_future()
        entry = (pair, limit, waiter)
        self._waiters.append(entry)
        try:
            return await waiter
        except asyncio.CancelledError:
            if entry in self._waiters:
                self._waiters.remove(entry)
            elif waiter.done() and not waiter.cancelled():
                waiter.result()()  # granted while being cancelled: hand the slot back
            raise

    def _try(self, pair: PairRuns, limit: RunLimit) -> Release | None:
        if not pair.guaranteed_busy:
            pair.guaranteed_busy = True
            pair.running += 1
            return self._releaser(pair, guaranteed=True)
        if pair.running >= limit.resolve(self._pairs):
            return None
        if self._extra is not None and self._extras_running >= self._extra.resolve(self._pairs):
            return None
        self._extras_running += 1
        pair.running += 1
        return self._releaser(pair, guaranteed=False)

    def _releaser(self, pair: PairRuns, *, guaranteed: bool) -> Release:
        released = False

        def release() -> None:
            nonlocal released
            if released:
                return
            released = True
            pair.running -= 1
            if guaranteed:
                pair.guaranteed_busy = False
            else:
                self._extras_running -= 1
            self._wake()

        return release

    def _wake(self) -> None:
        """Grant every waiter that may run now, in arrival order."""
        for entry in list(self._waiters):
            pair, limit, waiter = entry
            if waiter.done():
                self._waiters.remove(entry)
                continue
            granted = self._try(pair, limit)
            if granted is not None:
                self._waiters.remove(entry)
                waiter.set_result(granted)
