"""How much work each agent has in flight, so a process-terminating failure is attributable (C7).

Three failure classes take a whole group down and none of them raises anything a handler could
catch: the cgroup memory limit is breached and the kernel kills the process, a native extension
crashes without unwinding, or the event loop is blocked and nothing is an error at all. No
amount of exception handling changes which of those kill a group -- it only changes how often.

What is left is attribution, and attribution has to be emitted *before* the failure, because
afterwards there is no process to emit it. So each agent reports how many dispatches it has in
progress. An OOM kill then has a last observation to be read against: the agent whose in-flight
count was climbing is the one to look at, and without this an OOM kill is indistinguishable
across a group's agents and the grouping dial cannot be turned in response to it.

Counted around the handler chain rather than at a transport edge, so it covers both transports
and the REST dispatch path with one measurement, and so it means "work this agent is doing"
rather than "messages this agent's client has taken".
"""

import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from opentelemetry.metrics import CallbackOptions, Observation

from ...component.namespace import ROOT_LABEL
from .providers import agent_meter

logger = logging.getLogger(__name__)

IN_FLIGHT_GAUGE = "blueprint.namespace.inflight"
"""Dispatches an agent has in progress right now."""


class InFlightRegister:
    """Per-agent count of dispatches in progress, exported as an observable gauge."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def count(self, namespace: str) -> int:
        """How many dispatches ``namespace`` has in progress."""
        return self._counts.get(namespace, 0)

    def namespaces(self) -> tuple[str, ...]:
        """Every agent that has dispatched at least once, whether or not it is busy now."""
        return tuple(self._counts)

    def reset(self) -> None:
        """Forget every count. For tests; the instruments themselves are not removable."""
        self._counts.clear()

    @contextmanager
    def track(self, namespace: str) -> Iterator[None]:
        """Count one dispatch for ``namespace`` for as long as the block runs.

        The instrument is created the first time an agent is seen rather than at startup,
        because this is reached from the dispatch path and has no list of agents to iterate --
        and a first dispatch always happens long after the providers exist, which is the only
        ordering requirement creating one has.

        Args:
            namespace: The agent doing the work; ``""`` for the root.

        Yields:
            Nothing; the count is ambient.
        """
        if namespace not in self._counts:
            self._counts[namespace] = 0
            self._register(namespace)
        self._counts[namespace] += 1
        try:
            yield
        finally:
            self._counts[namespace] -= 1

    def _register(self, namespace: str) -> None:
        """Create ``namespace``'s gauge on its own meter, so it carries that agent's resource."""
        label = namespace or ROOT_LABEL

        def observe(_options: CallbackOptions) -> Iterable[Observation]:
            return [Observation(self._counts.get(namespace, 0), {"agent": label})]

        agent_meter(namespace, __name__).create_observable_gauge(
            IN_FLIGHT_GAUGE,
            callbacks=[observe],
            description="Dispatches this agent has in progress",
            unit="{dispatch}",
        )
        logger.debug("In-flight gauge registered for agent '%s'", label)


IN_FLIGHT = InFlightRegister()
"""The process's register. One per process because the gauge is, and because the dispatch path
that reads it is reached from components that have no way to be handed one."""
