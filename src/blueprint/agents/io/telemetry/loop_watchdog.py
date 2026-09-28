"""Noticing that the event loop has been blocked, and saying which agent was working.

The one group-wide failure class that is detectable from inside the process. A blocked loop is
not an error: no exception is raised, nothing is logged, the pod stays live, and every agent in
the group stops responding at once because there is one loop and they share it. Alone in a
process it shows up as latency in the one service that caused it; in a group it shows up as
latency in twenty services, nineteen of which did nothing wrong.

Two mechanisms, because the two environments can afford different things:

- **Development** turns on asyncio's own debug mode, which reports the exact callback that ran
  too long, with its source location. It is the better diagnostic by far and it is too
  expensive to leave on: debug mode wraps coroutine creation and keeps tracebacks for every
  task.
- **Production** runs this watchdog instead. It sleeps for a known interval and measures how
  much longer than that the sleep actually took; the excess is time the loop spent unable to
  run anything. It cannot name the callback -- by the time it runs again, the callback has
  returned -- so it names the agents that had work in flight, which is the set the culprit is
  in.

Naming candidates rather than the culprit is the honest shape here, and it is still the
difference between "the pod was slow" and "one of these two agents blocked the loop for four
seconds". Turning debug mode on in production to get the exact answer is available and
deliberate: set ``event_loop_debug`` and accept the cost.
"""

import asyncio
import logging
from collections.abc import Mapping

from ...component.namespace import ROOT_LABEL
from .inflight import IN_FLIGHT

logger = logging.getLogger(__name__)

WATCHDOG_ENABLED_KEY = "event_loop_watchdog_enabled"
WATCHDOG_INTERVAL_KEY = "event_loop_watchdog_interval_seconds"
BLOCK_THRESHOLD_KEY = "event_loop_block_threshold_seconds"
SLOW_CALLBACK_KEY = "event_loop_slow_callback_seconds"
DEBUG_KEY = "event_loop_debug"

DEFAULT_INTERVAL_SECONDS = 1.0
"""How often the watchdog wakes. Once a second costs one timer callback and one subtraction."""

DEFAULT_BLOCK_THRESHOLD_SECONDS = 1.0
"""How much lag is worth reporting in production.

A second is far above ordinary scheduling jitter and far below the point at which a probe times
out, so it catches a real block without reporting a busy loop as a broken one.
"""

DEFAULT_SLOW_CALLBACK_SECONDS = 0.2
"""asyncio's own threshold in development, where the exact callback is worth the overhead."""


def configure_loop_debug(config: Mapping[str, object] | object, *, development: bool) -> bool:
    """Turn on asyncio debug mode where it is wanted, and report whether it was turned on.

    Args:
        config: The application's configuration, read with ``get``.
        development: Whether this process is running in the development environment, which is
            what makes the debug mode's cost acceptable by default.

    Returns:
        Whether debug mode is now on, so the caller can skip the watchdog: with debug mode on,
        asyncio reports the blocking callback itself and the watchdog would only add a vaguer
        second line about the same event.
    """
    getter = getattr(config, "get", None)
    enabled = bool(getter(DEBUG_KEY, development)) if callable(getter) else development
    if not enabled:
        return False

    threshold = float(getter(SLOW_CALLBACK_KEY, DEFAULT_SLOW_CALLBACK_SECONDS)) if callable(getter) else DEFAULT_SLOW_CALLBACK_SECONDS
    loop = asyncio.get_running_loop()
    loop.set_debug(True)
    loop.slow_callback_duration = threshold
    logger.info("Event loop debug mode is on; a callback running longer than %.2fs will be reported by asyncio", threshold)
    return True


class LoopWatchdog:
    """Reports how long the event loop was unable to run anything, and who had work at the time."""

    def __init__(self, interval_seconds: float = DEFAULT_INTERVAL_SECONDS, threshold_seconds: float = DEFAULT_BLOCK_THRESHOLD_SECONDS):
        """Create the watchdog.

        Args:
            interval_seconds: How often to wake and measure.
            threshold_seconds: How much lag is reported. Lag is measured against the interval,
                so this is genuinely "time the loop could not run", not "time since the last
                check".
        """
        self._interval = interval_seconds
        self._threshold = threshold_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """Whether the watchdog task is running."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start watching. A second call does nothing."""
        if self.running:
            return
        self._task = asyncio.create_task(self._watch())
        # C7 applies to this task like any other the framework starts: a watchdog that died
        # silently would leave the process with no blocked-loop detection and no sign of it.
        self._task.add_done_callback(self._report_failure)
        logger.info("Event loop watchdog started: reporting a block longer than %.2fs", self._threshold)

    async def stop(self) -> None:
        """Stop watching."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: B014 -- shutdown must not raise
            pass
        self._task = None

    async def _watch(self) -> None:
        """Sleep, measure the overshoot, and report it if it is large enough."""
        loop = asyncio.get_running_loop()
        while True:
            before = loop.time()
            await asyncio.sleep(self._interval)
            lag = loop.time() - before - self._interval
            if lag >= self._threshold:
                self._report(lag)

    def _report(self, lag: float) -> None:
        """Log the block, naming the agents that had work in flight when it happened.

        In flight *now*, which is a moment after the block rather than during it -- the
        watchdog could not run while the loop was blocked, so there is no during. A handler
        that blocked and then returned is therefore missed by the attribution while the block
        itself is still reported, which is why the message says "had work in flight" rather
        than naming a culprit.
        """
        busy = [namespace or ROOT_LABEL for namespace in IN_FLIGHT.namespaces() if IN_FLIGHT.count(namespace)]
        logger.error(
            "The event loop was blocked for %.2fs, which stalls every agent in this process. Agents with work in "
            "flight: %s. Turn on '%s' to have asyncio name the callback.",
            lag,
            ", ".join(busy) or "none",
            DEBUG_KEY,
        )

    @staticmethod
    def _report_failure(task: asyncio.Task[None]) -> None:
        """Log an exception that ended the watchdog task (C7)."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("The event loop watchdog stopped with an exception: %s", exc, exc_info=exc)
