"""Handler chain for executing event handlers in priority order."""

import logging
import time
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace

from ..component.component import Component, traced
from ..component.namespace import ROOT_LABEL, ROOT_NAMESPACE
from ..models.events import CloudEvent, HandlerResult
from ..utils import parse_bool

logger = logging.getLogger(__name__)

DUPLICATE_CONTEXT_KEY = "idempotency_duplicate"
"""Context key set to ``True`` when dispatch was skipped because the event was seen before.

The chain returns ``None`` for a duplicate exactly as it does for an event no handler
wanted, and both acknowledge -- but they are not the same outcome, and the transport edge
counts them apart. It travels in ``context`` rather than in ``ProcessingStatus`` because
that enum is normative in spec sec. 7.2: it carries two values so that no failure can
reach the transport as a returned value, and a third one would invite exactly that.
"""

IDEMPOTENCY_CACHE_NAMESPACE = "idempotency"
"""Cache namespace holding the seen-event markers, kept away from application data."""


@dataclass(frozen=True)
class IdempotencyPolicy:
    """Resolved dedup settings (spec sec. 7.4).

    ``ttl`` is meaningless while ``enabled`` is ``False`` and is then zero. The two are
    held together because a dedup window without a lifetime is not a policy: entries that
    never expire turn the cache into an unbounded log of every event the agent ever saw.
    """

    enabled: bool
    ttl: int


class HandlerChain(Component):
    """Executes registered event handlers in priority order.

    Retrieves handlers from the component registry and processes events
    through them using the chain-of-responsibility pattern. Stops at the
    first handler that returns a non-None result. Re-raises any exception
    from handler execution.

    Idempotency
    ~~~~~~~~~~~
    At-least-once delivery is permanent (spec sec. 7.4): a handler that finishes and then
    cannot acknowledge has already committed its side effects, and the broker redelivers.
    Whether replaying that is *correct* is a property of the product, not of the framework,
    so dedup is opt-in and off by default -- ``idempotency_enabled``, with the window in
    ``idempotency_ttl``.

    When it is on, the chain claims a marker keyed on the event before dispatching and
    skips the dispatch if the marker is already there. A failed dispatch releases the
    claim, because the failure naks and the redelivery must be allowed to run: a claim
    kept across a failure would turn every retry into a silent no-op.

    The claim is check-then-set, not a lock. Two replicas handed the same event at the
    same instant can both pass the check, and a cache that is unreachable fails open --
    both dispatch. This narrows the duplicate window; it does not close it, and a handler
    whose side effects must never repeat still needs its own reconciliation.

    Config keys
    ~~~~~~~~~~~
    ``idempotency_enabled`` (bool, default ``False``): opt into dedup.
    ``idempotency_ttl`` (int, no default): seconds a seen-event marker is kept. Required
    when dedup is enabled, and deliberately without a default -- see ``_resolve_idempotency_policy``.

    One chain per agent
    ~~~~~~~~~~~~~~~~~~~
    A chain belongs to a namespace, and everything it reaches is that agent's: the handlers it
    dispatches to, the configuration the dedup policy is read from, and the cache partition the
    markers are claimed in. None of that is threaded through this class -- it all follows from
    ``Component.registry`` and ``Component.config`` handing a component its own namespace's view
    -- so the namespace appears here exactly once, in the constructor.

    That is also why a chain cannot be shared. Two agents in one process have their own handler
    sets and may have different ``idempotency_ttl`` values, and a shared chain would resolve one
    policy and dispatch to both agents' handlers.
    """

    def __init__(self, namespace: str = ROOT_NAMESPACE) -> None:
        """Initialize the handler chain for one agent.

        Args:
            namespace: The agent whose handlers this chain dispatches to, and whose
                configuration and cache it reads. ``""`` is the root, which is the whole of a
                single-agent application.

        Raises:
            ValueError: if ``namespace`` is not a legal namespace.
        """
        super().__init__(should_register=False, namespace=namespace)
        self._policy: IdempotencyPolicy | None = None

    async def on_startup(self) -> None:
        """Resolve the idempotency policy so a bad setting fails startup, not a delivery."""
        self._policy = self._resolve_idempotency_policy()
        if self._policy.enabled:
            logger.info(
                "Event deduplication is enabled for namespace '%s' with a %d second window",
                self.namespace or ROOT_LABEL,
                self._policy.ttl,
            )

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    @traced("event")
    async def process(self, event: CloudEvent[Any], context: dict[str, Any]) -> Any | HandlerResult | list[HandlerResult] | None:
        """Process event through all registered handlers in priority order.

        Args:
            event: The CloudEvent to process
            context: Processing context dictionary

        Returns:
            Result from first handler that returns non-None, or None -- including when the
            event was already seen and dispatch was skipped

        Raises:
            Exception: Re-raises any exception from handler execution
        """
        # Resolved here as well as in on_startup because a chain used outside AppBuilder
        # never has its startup called, and inheriting "dedup is off" from a missed wiring
        # step is the one failure this feature must not have.
        policy = self._policy
        if policy is None:
            policy = self._policy = self._resolve_idempotency_policy()

        if not self._claim(event, policy):
            context[DUPLICATE_CONTEXT_KEY] = True
            trace.get_current_span().set_attribute("event.duplicate", True)
            logger.info("Skipping event '%s' from '%s': already processed within the dedup window", event.id, event.source)
            return None

        try:
            return await self._dispatch(event, context)
        except Exception:
            self._release(event, policy)
            raise

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch(self, event: CloudEvent[Any], context: dict[str, Any]) -> Any | HandlerResult | list[HandlerResult] | None:
        """Run this agent's handlers in priority order until one returns a result.

        The namespace is passed explicitly rather than left to the registry view's default,
        and the difference only shows up in a grouped process. On the root registry an omitted
        namespace means *every* namespace, so a root chain would dispatch one agent's event
        through every other agent's handlers. Naming the namespace makes the root chain mean
        strictly the root, which in a single-agent application is every handler there is.

        There is no fallback to root handlers either. A handler registered at the root of a
        grouped process would otherwise run for every agent in it, and nothing in a handler's
        code could tell its author that is happening.
        """
        handlers = sorted(self.registry.get_event_handler(namespace=self.namespace))
        span = trace.get_current_span()
        span.set_attribute("handlers.count", len(handlers))
        span.set_attribute("agent", self.namespace or ROOT_LABEL)

        logger.debug("Processing event through %d handlers in namespace '%s'", len(handlers), self.namespace or ROOT_LABEL)

        for handler in handlers:
            try:
                if await handler.can_handle(event, context):
                    logger.info("Handler '%s' handling event '%s'", handler.name, event.type)
                    result = await handler.handle(event, context)
                    if result is not None:
                        span.set_attribute("handler.processed_by", handler.name)
                        return result
                    logger.info("Handler '%s' passed event '%s' to next handler", handler.name, event.type)

            except Exception as e:
                logger.error("Handler '%s' failed: %s", handler.name, str(e), exc_info=True)
                span.record_exception(e)
                raise

        logger.warning("No handler in namespace '%s' processed event '%s'", self.namespace or ROOT_LABEL, event.type)
        return None

    # ------------------------------------------------------------------
    # Idempotency (P4)
    # ------------------------------------------------------------------

    def _claim(self, event: CloudEvent[Any], policy: IdempotencyPolicy) -> bool:
        """Record that this event is being processed, and report whether to dispatch it.

        Returns:
            ``True`` if the event should be dispatched -- dedup is off, the event cannot be
            keyed, or this is the first time it has been seen. ``False`` if a marker for it
            is already in the cache, meaning some earlier delivery already ran the chain.
        """
        if not policy.enabled:
            return True

        key = self._idempotency_key(event)
        if key is None:
            return True

        cache = self.registry.cache_service
        if cache.exists(key, namespace=IDEMPOTENCY_CACHE_NAMESPACE):
            return False

        cache.set(
            key,
            {"seen_at": time.time(), "event_type": event.type},
            namespace=IDEMPOTENCY_CACHE_NAMESPACE,
            ttl=policy.ttl,
        )
        return True

    def _release(self, event: CloudEvent[Any], policy: IdempotencyPolicy) -> None:
        """Drop the marker after a failed dispatch so the redelivery is allowed to run.

        The claim is taken before dispatch, which is the only point at which it can stop a
        concurrent duplicate. That means a dispatch that raises leaves a marker behind for
        an event that was *not* processed, and the nak this failure produces sends the very
        same event back. Without this the retry would be swallowed as a duplicate and the
        message would be lost after ``max_deliver`` attempts that never ran a handler.
        """
        if not policy.enabled:
            return

        key = self._idempotency_key(event)
        if key is None:
            return

        self.registry.cache_service.delete(key, namespace=IDEMPOTENCY_CACHE_NAMESPACE)
        logger.debug("Released the dedup marker for event '%s' after a failed dispatch", event.id)

    @staticmethod
    def _idempotency_key(event: CloudEvent[Any]) -> dict[str, str] | None:
        """Build the dedup key, or ``None`` if the event cannot be identified.

        Keyed on ``source`` as well as ``id``. The CloudEvents specification requires an
        ``id`` to be unique only *within* a source, so two producers may legitimately both
        emit id ``"1"``, and keying on the id alone would let one agent's event suppress
        another's. Sent as a dict because the cache sorts a dict by key before hashing it,
        which a list of the two values would not preserve.
        """
        event_id = str(getattr(event, "id", "") or "").strip()
        source = str(getattr(event, "source", "") or "").strip()
        if not event_id or not source:
            logger.warning(
                "Cannot deduplicate an event without both an id and a source (id=%r, source=%r); dispatching it",
                event_id,
                source,
            )
            return None
        return {"id": event_id, "source": source}

    def _resolve_idempotency_policy(self) -> IdempotencyPolicy:
        """Read and validate the dedup settings (spec sec. 7.4).

        ``idempotency_ttl`` has no default on purpose. The window has to outlast the
        redelivery window it is there to cover -- under JetStream that is
        ``nats_ack_wait * nats_max_deliver``, under Dapr it is whatever the component's
        retry policy says -- and neither number is one this layer can read. Choosing a
        value here would mean shipping a dedup window that silently expires before the last
        redelivery arrives, which looks exactly like dedup not working. Enabling dedup is
        therefore two keys, and the second one is the decision spec sec. 7.4 requires the
        author to make.

        Raises:
            ValueError: if ``idempotency_enabled`` is not a boolean, if it is on without a
                positive ``idempotency_ttl``, or if it is on with no cache registered --
                there would be nowhere to keep the markers, and dedup would be silently off.
        """
        enabled = self._read_bool("idempotency_enabled", False)
        if not enabled:
            return IdempotencyPolicy(enabled=False, ttl=0)

        raw_ttl = self.config.get("idempotency_ttl", None)
        if raw_ttl is None:
            raise ValueError(
                "'idempotency_enabled' is true but 'idempotency_ttl' is not set. It is the number of "
                "seconds a processed event is remembered, and it must outlast the broker's redelivery "
                "window ('nats_ack_wait' * 'nats_max_deliver' on JetStream), or a redelivery arrives "
                "after the marker has expired and is processed again."
            )
        try:
            ttl = int(raw_ttl)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Config key 'idempotency_ttl' must be an integer number of seconds, got {raw_ttl!r}.") from exc
        if ttl <= 0:
            raise ValueError(f"'idempotency_ttl' must be greater than 0, got {ttl}. It is the dedup window, in seconds.")

        if not self.registry.has_cache():
            raise ValueError(
                "'idempotency_enabled' is true but no cache is registered, so there is nowhere to record "
                "the events already processed. Add '.with_cache()' to the AppBuilder chain."
            )

        return IdempotencyPolicy(enabled=True, ttl=ttl)

    def _read_bool(self, key: str, default: bool) -> bool:
        """Read a boolean config key, accepting the strings an environment variable delivers."""
        return parse_bool(self.config.get(key, default), key)
