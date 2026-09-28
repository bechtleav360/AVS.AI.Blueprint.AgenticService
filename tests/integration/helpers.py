"""Waiting, done once so that no broker test has to invent it.

A broker is asynchronous in the sense that matters here: nothing a test asks for is true at the
moment it asks. The connection is established by a background task, a subscription is registered
on the server a round trip later, and a handler runs when the delivery arrives. Every assertion
against a real broker is therefore preceded by a wait, and the shape of that wait decides what a
failure tells you.
"""

import asyncio
from collections.abc import Awaitable, Callable


async def wait_until(predicate: Callable[[], bool], *, timeout: float, description: str) -> None:
    """Poll ``predicate`` until it is true, or fail saying what never happened.

    The alternative -- a fixed ``asyncio.sleep`` -- is either too short on a loaded machine or
    wasted on every run, and when it is too short the failure blames the assertion that follows
    rather than the wait. ``description`` is what makes the timeout readable: it is the only
    thing the reader of a CI log has.

    Args:
        predicate: Checked repeatedly; must not block.
        timeout: Seconds to wait before failing.
        description: What is being waited for, phrased to follow "waiting for".

    Raises:
        AssertionError: if the timeout passes with the predicate still false.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"Timed out after {timeout}s waiting for {description}")


async def poll_until(
    predicate: Callable[[], Awaitable[bool]],
    *,
    timeout: float,
    description: str,
) -> None:
    """Like :func:`wait_until`, for a condition that has to be asked of the broker.

    Separate rather than a flag on one function, because the two take different things: a
    synchronous predicate reads state the process already holds, and this one makes a request per
    attempt -- so the interval is longer, and a caller has to know which it is using.

    Args:
        predicate: Awaited repeatedly until it returns true.
        timeout: Seconds to wait before failing.
        description: What is being waited for, phrased to follow "waiting for".

    Raises:
        AssertionError: if the timeout passes with the predicate still false.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.2)
    raise AssertionError(f"Timed out after {timeout}s waiting for {description}")
