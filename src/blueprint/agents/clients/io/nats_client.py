"""NATS client implementation for eventing."""

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import nats
from nats.aio.client import Client as NatsClient
from nats.js import api as js_api
from nats.js.client import JetStreamContext
from nats.js.errors import NotFoundError
from opentelemetry.metrics import Counter

from ...component.namespace import ROOT_LABEL, ROOT_NAMESPACE
from ...deployment import deployment_group, pod_identity
from ...io.telemetry.providers import agent_meter
from ...models.api import ComponentHealth
from ...models.errors import DeliveryDisposition, disposition_for
from ...models.events import CloudEvent
from .io_client_base import IOClientBase, validate_subject_segment

logger = logging.getLogger(__name__)

DEAD_LETTERED_COUNTER = "blueprint.events.dead_lettered"
"""Events the framework gave up on, whether or not their payload was kept.

Dead-lettering was logged and counted nowhere, so "how many messages did we give up on today"
could not be answered from metrics -- and a dead letter is the one delivery outcome that has
no other trace in the running system: it is not a retry that eventually succeeds, and it is
not an error a caller sees. ``reason`` separates a payload that was rejected as unprocessable
from one whose redeliveries ran out, and ``kept`` says whether the payload survived, because a
deployment with no dead-letter subject configured is losing them.
"""


@dataclass(frozen=True)
class ConsumerTuning:
    """JetStream consumer settings, resolved once from config (spec sec. 7.3).

    Held as one object because the four values only make sense together: ``ack_wait``
    decides when an unacknowledged message comes back, ``max_ack_pending`` decides how
    many can be waiting at once, ``max_deliver`` decides how often it comes back before
    the framework gives up, and ``dead_letter_subject`` decides where it goes when that
    happens.
    """

    ack_wait: float
    max_ack_pending: int
    max_deliver: int
    dead_letter_subject: str


class NATSClient(IOClientBase):
    """NATS client for subscribing to and publishing CloudEvents.

    Managed subscription lifecycle
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Call ``subscribe(topic_callbacks)`` once at startup with the full
    ``{topic: callback}`` mapping.  The client fires a background retry
    task that connects to the broker and subscribes to every topic.
    ``subscriptions_ready`` becomes ``True`` once all subscriptions are
    active; ``health_check()`` reflects this state so the readiness probe
    keeps the pod out of service rotation until then.

    On disconnect the NATS library fires ``_on_disconnected``, which clears
    the ready flag.  On reconnect ``_on_reconnected`` re-subscribes (JetStream
    only — Core NATS re-subscribes automatically) and restores the flag.

    One connection per namespace
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    A client belongs to one namespace (spec sec. 6), so a process hosting three
    agents opens three connections rather than multiplexing one. That confines
    the two failures that are per-connection: a dropped connection strands the
    acknowledgements of only that namespace's in-flight messages, and a
    slow-consumer kick removes only the namespace that flooded its buffer. It is
    **not** a durability mechanism -- JetStream pending state lives on the server,
    so what the topology decides is how many namespaces repeat work after a drop.

    Each connection is named ``f"{namespace}.{group}.{pod}"``, which is what makes
    a pod's contents legible in ``/connz``; before this, every connection the
    framework opened was anonymous. An absent segment becomes a bracketed placeholder
    (``<root>``, ``<ungrouped>``, ``<unknown-pod>``) that no real namespace, group or
    pod can produce, so a missing value never reads as a present one. The name contains
    the pod, so it must never reach queue-group or durable naming (C1) -- those two are
    the only broker-side identifiers, and both derive from the namespace alone.

    Queue group
    ~~~~~~~~~~~
    Every Core NATS subscription joins a queue group, so exactly one replica
    receives any given message.  The name is resolved once in ``subscribe()``
    and is a pure function of the agent's own identity -- never of the pod,
    container or replica it happens to run in.

    One name covers every topic because a group is keyed by *(subject, queue
    name)*: subscriptions sharing this name on different subjects are separate
    groups, so unrelated event types never compete for the same delivery.  The
    exception is a subject overlapping another of this client's own subjects
    (a wildcard plus a literal it covers), where one message matches two of its
    subscriptions -- the server is expected to merge them into one group and
    deliver once, to either callback.  Unverified against a real broker; see the
    feature changelog's broker-test open point.

    JetStream consumer
    ~~~~~~~~~~~~~~~~~~
    Under JetStream the durable consumer is created explicitly rather than left to
    ``js.subscribe``, because every setting that makes a consumer safe to share lives on
    ``ConsumerConfig``: the deliver group that stops each replica seeing every message,
    the ``ack_wait`` that must outlast a slow handler, the ``max_ack_pending`` window and
    the ``max_deliver`` limit after which a message is dead-lettered rather than dropped.
    An existing consumer is never rewritten -- a durable's filter and deliver group are
    broker-side state, and recreating one either replays or gaps.

    Config keys
    ~~~~~~~~~~~
    ``event_client_max_retries`` (int, default -1): retries after first failure;
    ``-1`` = indefinite, ``0`` = single attempt.
    ``event_client_retry_delay`` (float, default 5.0): seconds between retries.
    ``event_client_drain_timeout`` (float, default 30.0): seconds allowed for in-flight
    handlers to finish during shutdown.
    ``nats_ack_wait`` (float, default 300.0): seconds the broker waits for an
    acknowledgement before redelivering. Must exceed p99 handler duration.
    ``nats_max_ack_pending`` (int, default 16): unacknowledged messages allowed at once
    across every replica sharing the consumer; ``-1`` = unlimited.
    ``nats_max_deliver`` (int, default 5): delivery attempts before a message is
    dead-lettered; ``-1`` = unlimited, which disables dead-lettering on exhaustion.
    ``nats_dead_letter_subject`` (str, default ``"<queue group>.dead-letter"``): where a
    message goes when the framework gives up on it; ``""`` disables it and loses the payload.
    """

    def __init__(self, namespace: str = ROOT_NAMESPACE) -> None:
        super().__init__(namespace=namespace)
        self._connection_name: str = ""
        self._nats_client: NatsClient | None = None
        self._js: JetStreamContext | None = None
        self._use_jetstream: bool = False
        self._subscriptions: list[Any] = []
        self._topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]] = {}
        self._queue_group: str = ""
        self._tuning: ConsumerTuning | None = None
        self._durables: dict[str, str] = {}
        self._subscriptions_ready: bool = False
        self._subscriptions_managed: bool = False
        self._retry_task: asyncio.Task[None] | None = None
        self._inflight: int = 0
        self._idle: asyncio.Event = asyncio.Event()
        self._idle.set()

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def subscriptions_ready(self) -> bool:
        """``True`` once all managed subscriptions are active."""
        return self._subscriptions_ready

    @cached_property
    def _dead_lettered(self) -> Counter:
        """This agent's dead-letter counter, created on first use rather than at construction.

        Cached rather than eager for the same reason ``Component.tracer`` is: a client is
        constructed by ``build()``, and the per-agent meter providers do not exist until the
        lifespan configures telemetry. An instrument created in ``__init__`` would be bound to
        the no-op global meter for the life of the process.
        """
        return agent_meter(self.namespace, __name__).create_counter(
            name=DEAD_LETTERED_COUNTER,
            description="Events this agent gave up on after exhausting redelivery or rejecting the payload",
            unit="{event}",
        )

    @property
    def queue_group(self) -> str:
        """Queue group joined by this client's subscriptions; ``""`` before ``subscribe()``."""
        return self._queue_group

    @property
    def inflight_handlers(self) -> int:
        """Number of message handlers currently executing."""
        return self._inflight

    @property
    def consumer_tuning(self) -> ConsumerTuning | None:
        """JetStream consumer settings resolved by ``subscribe()``; ``None`` on Core NATS."""
        return self._tuning

    @property
    def connection_name(self) -> str:
        """Name this connection reports to the broker; ``""`` before the first connect."""
        return self._connection_name

    # ------------------------------------------------------------------
    # Managed subscription API
    # ------------------------------------------------------------------

    async def subscribe(self, topic_callbacks: dict[str, Callable[[CloudEvent[Any]], Awaitable[None]]]) -> None:
        """Register all topic→callback mappings and start the background retry task.

        Returns immediately; connection and subscription happen in the background.
        """
        self._topic_callbacks = topic_callbacks
        self._queue_group = self._resolve_queue_group()
        if self.config.get("nats_use_jetstream", False):
            self._durables = self._resolve_durables(list(topic_callbacks))
            self._tuning = self._resolve_consumer_tuning(list(topic_callbacks))
        self._subscriptions_managed = True
        self._subscriptions_ready = False
        self._retry_task = asyncio.ensure_future(self._start_with_retry())
        self._retry_task.add_done_callback(self._on_retry_done)

    def _resolve_queue_group(self) -> str:
        """Return the queue group name, or raise if none can be derived.

        The name identifies the *agent*, not the process that hosts it: moving an agent
        into a different deployment group must not change which broker-side consumer it
        is (spec C1).

        A namespaced client therefore uses its namespace verbatim -- it was validated at
        construction, so it needs no checking or rewriting here -- and only the root namespace
        falls back to ``nats_queue_group`` then ``app_name`` -- which is what
        ``nats_queue_group`` is documented to be, "the queue group for the root namespace
        only". Without that branch every client in a process would resolve the same
        ``app_name``, and two co-hosted agents subscribing to one topic would form a
        single group and steal each other's messages: exactly one of them would see any
        given event.

        Resolved here rather than at subscription time so that a misconfiguration fails
        the caller's startup instead of disappearing into the background retry loop, which
        would retry a config error forever.

        Raises:
            ValueError: if neither key yields a non-empty name. NATS reads ``queue=""`` as
                "no queue group", which is precisely the every-replica-processes-every-message
                fan-out this exists to prevent, so there is no usable fallback.
            ValueError: if a configured name contains whitespace or a wildcard. ``nats-py``
                rejects such a queue name with ``BadSubjectError``, and an ``app_name`` like
                ``"My Service"`` was perfectly legal before subscriptions carried a queue group.
                A wildcard additionally reaches the default dead-letter subject, which is derived
                from this name. Reported here, naming the key and the value, rather than left to
                surface as a repeating ``BadSubjectError`` inside the background retry task. A
                *namespace* cannot reach this check: it is rejected at construction instead.
        """
        if self.namespace:
            return self.namespace

        for key in ("nats_queue_group", "app_name"):
            name = str(self.config.get(key, "") or "").strip()
            if not name:
                continue
            validate_subject_segment(name, source=f"The queue group (from '{key}')", subject=f"{name}.dead-letter")
            return name
        raise ValueError(
            "NATS subscriptions require a queue group: set 'nats_queue_group' or 'app_name'. "
            "Without one every replica processes every message."
        )

    # ------------------------------------------------------------------
    # Consumer settings (P3)
    # ------------------------------------------------------------------

    def _resolve_consumer_tuning(self, topics: list[str]) -> ConsumerTuning:
        """Read and validate the JetStream consumer settings (spec sec. 7.3).

        Resolved in ``subscribe()`` for the same reason the queue group is: a bad value
        must fail the caller's startup rather than disappear into the background retry
        task, which would retry a config error forever.

        Raises:
            ValueError: if a value is not a number, is zero, or is a negative value other
                than ``-1``.
        """
        ack_wait = self._read_float("nats_ack_wait", 300.0)
        if ack_wait <= 0:
            raise ValueError(f"'nats_ack_wait' must be greater than 0, got {ack_wait}. It is the redelivery timeout, in seconds.")

        max_ack_pending = self._read_int("nats_max_ack_pending", 16)
        if max_ack_pending == 0 or max_ack_pending < -1:
            raise ValueError(f"'nats_max_ack_pending' must be a positive count or -1 for unlimited, got {max_ack_pending}.")

        max_deliver = self._read_int("nats_max_deliver", 5)
        if max_deliver == 0 or max_deliver < -1:
            raise ValueError(f"'nats_max_deliver' must be a positive count or -1 for unlimited, got {max_deliver}.")
        if max_deliver == -1:
            logger.warning(
                "'nats_max_deliver' is -1, so a message that keeps failing is redelivered forever "
                "and never reaches the dead-letter subject. Set a positive limit to bound it."
            )

        return ConsumerTuning(
            ack_wait=ack_wait,
            max_ack_pending=max_ack_pending,
            max_deliver=max_deliver,
            dead_letter_subject=self._resolve_dead_letter_subject(topics),
        )

    def _resolve_dead_letter_subject(self, topics: list[str]) -> str:
        """Return the subject a given-up-on message is republished to, or ``""`` if disabled.

        Defaults to ``"<queue group>.dead-letter"``, so it is derived from the agent's own
        identity exactly as the queue group is (C1) and moving the agent between deployment
        groups does not move its dead letters.

        Raises:
            ValueError: if the subject contains whitespace or a wildcard -- it is published
                to, and neither is publishable.
            ValueError: if one of this client's own subscriptions would deliver it back.
                Dead-lettering onto a subject the same client consumes turns one failure
                into an unbounded loop, and the loop only appears under load.
        """
        configured = self.config.get("nats_dead_letter_subject", None)
        subject = f"{self._queue_group}.dead-letter" if configured is None else str(configured).strip()
        if not subject:
            return ""

        if any(char.isspace() for char in subject) or "*" in subject or ">" in subject:
            raise ValueError(
                f"Dead-letter subject '{subject}' contains whitespace or a wildcard. "
                "It is a subject the client publishes to, so it must name exactly one."
            )
        for topic in topics:
            if self._subject_matches(topic, subject):
                raise ValueError(
                    f"Dead-letter subject '{subject}' is delivered by this client's own subscription "
                    f"to '{topic}', so a dead-lettered message would come straight back and be "
                    "dead-lettered again. Set 'nats_dead_letter_subject' outside the subscribed subjects."
                )
        return subject

    def _resolve_durables(self, topics: list[str]) -> dict[str, str]:
        """Map every topic to the durable consumer name that will carry it.

        A durable belongs to one filter subject, so each topic needs its own name and no
        two topics may resolve to the same one. Both failure modes are config errors and
        are raised here rather than left to surface as a JetStream API error inside the
        retry loop.

        Raises:
            ValueError: if ``nats_durable_name`` is set while more than one topic is
                subscribed, or if two topics sanitise to the same durable name.
        """
        configured = str(self.config.get("nats_durable_name", "") or "").strip()
        if configured and len(topics) > 1:
            raise ValueError(
                f"'nats_durable_name' is set to '{configured}' but {len(topics)} topics are subscribed. "
                "A JetStream durable filters one subject, so one name cannot serve them all. "
                "Remove the key to derive a durable per topic."
            )
        if configured and self.namespace:
            logger.warning(
                "Namespace '%s' is using the configured durable name '%s'. A durable is broker-side state "
                "shared by everything that binds to it, so unless this key is scoped per namespace, every "
                "namespace in this process binds to the same consumer and they consume each other's events.",
                self.namespace,
                configured,
            )

        durables: dict[str, str] = {}
        for topic in topics:
            name = configured or self._durable_for(topic)
            clash = next((other for other, existing in durables.items() if existing == name), None)
            if clash is not None:
                raise ValueError(
                    f"Topics '{clash}' and '{topic}' both resolve to durable name '{name}'. "
                    "NATS allows no '.', '*', '>' or whitespace in a consumer name, so those "
                    "characters are replaced with '_'. Rename one of the topics."
                )
            durables[topic] = name
        return durables

    def _durable_for(self, topic: str) -> str:
        """Derive a legal durable consumer name from a subject.

        NATS rejects ``.``, ``*``, ``>`` and whitespace in a consumer name, so the dotted
        subjects that are idiomatic in NATS -- ``orders.created`` -- cannot serve as one
        directly. Only the *topic* is rewritten: the namespace was validated against an
        alphabet a consumer name already accepts, so it is used as it was declared.

        A namespaced client puts its namespace in front, for the same reason its queue
        group is the namespace (C1): two co-hosted agents subscribing to one topic each
        need their own consumer, or the broker hands every message to whichever of them
        binds first. The root namespace keeps the bare ``<topic>-durable``, so no existing
        consumer is renamed and no deployment of this change becomes a consumer migration.

        The result -- ``orders-orders_created-durable`` for namespace ``orders`` on topic
        ``orders.created`` -- reads back unambiguously because ``-`` is excluded from the
        namespace alphabet: the first ``-`` is always the boundary between the namespace and
        the topic. Were it allowed, ``orders-eu`` on ``created`` and ``orders`` on
        ``eu-created`` would name one consumer and two agents would share it.
        """
        prefix = f"{self.namespace}-" if self.namespace else ""
        return f"{prefix}{re.sub(r'[.*>\s]', '_', topic)}-durable"

    @staticmethod
    def _subject_matches(pattern: str, subject: str) -> bool:
        """Return whether a NATS subject filter would deliver a given subject.

        ``*`` matches exactly one token, ``>`` matches one or more and only as the final
        token. Used to prove the dead-letter subject is outside what this client consumes.
        """
        pattern_tokens = pattern.split(".")
        subject_tokens = subject.split(".")
        for index, token in enumerate(pattern_tokens):
            if token == ">":
                return index < len(subject_tokens)
            if index >= len(subject_tokens):
                return False
            if token != "*" and token != subject_tokens[index]:
                return False
        return len(pattern_tokens) == len(subject_tokens)

    def _read_float(self, key: str, default: float) -> float:
        raw = self.config.get(key, default)
        try:
            return float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Config key '{key}' must be a number, got {raw!r}.") from exc

    def _read_int(self, key: str, default: int) -> int:
        raw = self.config.get(key, default)
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Config key '{key}' must be an integer, got {raw!r}.") from exc

    # ------------------------------------------------------------------
    # Connection identity (P6)
    # ------------------------------------------------------------------

    def _resolve_connection_name(self) -> str:
        """Return the name this connection reports to the broker (spec sec. 6).

        ``f"{namespace}.{group}.{pod}"``: which agent, which deployment group, which
        replica. It exists for attribution only -- ``nats.connect()`` was previously
        called with no ``name=`` at all, so every connection the framework opened showed
        up anonymous in ``/connz`` and a pod hosting several agents was unreadable.

        All three positions are always filled, using a placeholder where a value is
        absent, so the name cannot degenerate into ``"..pod-7"`` and "no group" stays
        distinguishable from "a group whose name is empty".

        **This value must never reach the queue group or the durable name.** It contains
        the pod, so a consumer identity derived from it would change on every restart and
        on every regrouping, which is precisely what C1 forbids. It is deliberately not
        stored anywhere those two are resolved from.
        """
        namespace = self.namespace or ROOT_LABEL
        return f"{namespace}.{deployment_group()}.{pod_identity()}"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _is_connected(self) -> bool:
        return self._nats_client is not None and not self._nats_client.is_closed and self._nats_client.is_connected

    async def connect(self) -> None:
        """Connect to the NATS server, registering disconnect/reconnect callbacks."""
        if self._nats_client is not None and not self._nats_client.is_closed:
            return

        nats_url = self.config.get("nats_url", "nats://localhost:4222")
        self._connection_name = self._resolve_connection_name()
        try:
            self._nats_client = await nats.connect(
                nats_url,
                name=self._connection_name,
                max_reconnect_attempts=self.config.get("nats_max_reconnect_attempts", 5),
                reconnect_time_wait=self.config.get("nats_reconnect_time_wait", 2),
                connect_timeout=10,
                disconnected_cb=self._on_disconnected,
                reconnected_cb=self._on_reconnected,
            )
            self._client = self._nats_client
            self._use_jetstream = self.config.get("nats_use_jetstream", False)
            if self._use_jetstream:
                try:
                    self._js = self._nats_client.jetstream()
                    logger.info("Connected to NATS server with JetStream at %s as '%s'", nats_url, self._connection_name)
                except Exception as e:
                    logger.warning("JetStream initialization failed, falling back to Core NATS: %s", str(e))
                    self._use_jetstream = False

            if not self._use_jetstream:
                logger.info("Connected to NATS server (Core NATS) at %s as '%s'", nats_url, self._connection_name)
        except Exception as e:
            logger.error("Failed to connect to NATS: %s", str(e))
            raise

    async def pause_consumption(self) -> None:
        """Drain this agent's subscriptions so its events redeliver elsewhere (C4).

        Drained rather than unsubscribed, for the same reason shutdown drains: a drain stops
        new deliveries while letting the ones already in the client's buffer reach their
        handler and be acknowledged over the connection that delivered them. An unsubscribe
        strands those, and every one of them redelivers.

        The connection stays open. See :meth:`IOClientBase.pause_consumption` for why closing
        it would make the pause permanent, and :meth:`health_check` for the other half of that.
        """
        if self._consumption_paused:
            return
        self._consumption_paused = True
        self._subscriptions_ready = False
        if self._nats_client is not None:
            timeout = float(self.config.get("event_client_drain_timeout", 30.0))
            deadline = asyncio.get_running_loop().time() + timeout
            await self._drain_subscriptions(deadline)
            await self._await_inflight(deadline)
        logger.error(
            "Agent '%s' stopped consuming: its subscriptions are drained while it is degraded, so its events "
            "redeliver to a healthy replica",
            self.namespace or ROOT_LABEL,
        )

    async def resume_consumption(self) -> None:
        """Re-subscribe this agent's topics after its health checks pass again.

        Nothing is retried here: a failure to re-subscribe leaves the client paused, and the
        next health poll finds the agent healthy again and calls this again. That is the whole
        retry, and it is bounded by the poll interval rather than by a loop of its own.
        """
        if not self._consumption_paused:
            return
        self._consumption_paused = False
        if not self._subscriptions_managed or self._nats_client is None:
            return
        try:
            await self._subscribe_all()
        except Exception as exc:
            self._consumption_paused = True
            logger.error("Agent '%s' could not resume consuming: %s", self.namespace or ROOT_LABEL, exc, exc_info=True)
            return
        self._subscriptions_ready = True
        logger.info("Agent '%s' resumed consuming: %d subscription(s) restored", self.namespace or ROOT_LABEL, len(self._subscriptions))

    async def close(self) -> None:
        """Stop consuming, let in-flight handlers finish, then close the connection.

        The order is load-bearing. An acknowledgement travels over the same connection
        that delivered the message, so closing the connection while a handler is still
        running strands that acknowledgement and guarantees redelivery. Subscriptions
        are drained first, in-flight handlers then get until ``event_client_drain_timeout``
        to finish, and only then is the connection closed. The timeout bounds the whole
        sequence, so shutdown stays inside a pod's termination grace period.
        """
        self._subscriptions_ready = False

        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task

        if self._nats_client is not None:
            timeout = float(self.config.get("event_client_drain_timeout", 30.0))
            deadline = asyncio.get_running_loop().time() + timeout
            await self._drain_subscriptions(deadline)
            await self._await_inflight(deadline)

            await self._nats_client.close()
            self._nats_client = None
            self._js = None
            self._client = None

    # ------------------------------------------------------------------
    # Internal -- shutdown
    # ------------------------------------------------------------------

    async def _drain_subscriptions(self, deadline: float) -> None:
        """Stop new deliveries while letting already-queued messages reach their handler.

        Falls back to an immediate unsubscribe if a drain fails or outlives the deadline,
        so one stuck subscription cannot hold up shutdown.
        """
        for sub in self._subscriptions:
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            try:
                await asyncio.wait_for(sub.drain(), timeout=remaining)
            except TimeoutError:
                logger.warning("Draining a NATS subscription outlived the shutdown deadline; unsubscribing instead")
                await self._force_unsubscribe(sub)
            except Exception as e:
                logger.warning("Failed to drain a NATS subscription (%s); unsubscribing instead", e)
                await self._force_unsubscribe(sub)
        self._subscriptions.clear()

    @staticmethod
    def _decode_message(msg: Any, topic: str) -> CloudEvent[Any] | None:
        """Decode a broker message into a CloudEvent, or ``None`` if the payload is unusable.

        Kept separate from dispatch because the two failures have opposite dispositions. A
        payload that cannot become a CloudEvent will not become one on redelivery either, so
        it is terminal for that message rather than retryable: P2 terms here, and naks a
        dispatch failure (spec sec. 7.2).
        """
        try:
            event_data = json.loads(msg.data.decode())
            return CloudEvent(**event_data)
        except Exception as ex:
            logger.error("Discarding unparseable message on topic '%s': %s", topic, ex)
            return None

    @staticmethod
    async def _force_unsubscribe(sub: Any) -> None:
        with contextlib.suppress(Exception):
            await sub.unsubscribe()

    async def _await_inflight(self, deadline: float) -> None:
        """Give handlers that are still running a bounded chance to finish."""
        if self._inflight == 0:
            return

        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        logger.debug("Waiting up to %.1fs for %d in-flight NATS handler(s)", remaining, self._inflight)
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=remaining)
        except TimeoutError:
            logger.error(
                "Shutdown deadline reached with %d NATS handler(s) still running; their messages will be redelivered",
                self._inflight,
            )

    def _enter_handler(self) -> None:
        self._inflight += 1
        self._idle.clear()

    def _exit_handler(self) -> None:
        self._inflight = max(0, self._inflight - 1)
        if self._inflight == 0:
            self._idle.set()

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, topic: str, event: CloudEvent[Any], routing_key: str | None = None) -> None:
        """Publish a CloudEvent to a topic.

        Args:
            topic: The topic, used for event routing.
            event: The CloudEvent to publish.
            routing_key: Ignored — NATS does not use routing keys.
        """
        client = await self.client

        try:
            event_data = json.dumps(dict(event)).encode()

            if self._use_jetstream and client.jetstream():
                ack = await client.jetstream().publish(topic, event_data)
                logger.debug("Published event to JetStream topic '%s' (seq: %d): %s", topic, ack.seq, event.id)
            else:
                await client.publish(topic, event_data)
                logger.debug("Published event to Core NATS topic '%s': %s", topic, event.id)

        except Exception as e:
            logger.error("Failed to publish event to topic '%s': %s", topic, str(e))
            raise

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ComponentHealth:
        """Return healthy only when connected and all managed subscriptions are active.

        **A paused client reports healthy.** The pause is a consequence of the agent being
        degraded (C4), not a cause of it, and the check that actually failed is still in the
        readiness payload saying so. Reporting the pause as unhealthy would make it
        self-sustaining: the agent could never be seen to recover, so consumption would never
        resume, and a transient Redis outage would take the agent off its topics permanently.
        """
        if not self._is_connected():
            return ComponentHealth(status="unhealthy", message="NATS client not connected")
        if self._consumption_paused:
            return ComponentHealth(status="healthy", message="connected; consumption paused while this agent is degraded")
        if self._subscriptions_managed and not self._subscriptions_ready:
            return ComponentHealth(status="unhealthy", message="connected but subscriptions not yet established")
        server_info = self._nats_client.connected_url  # type: ignore[union-attr]
        sub_info = f" ({len(self._subscriptions)} subscriptions active)" if self._subscriptions else ""
        return ComponentHealth(status="healthy", message=f"Connected to NATS server at {server_info}{sub_info}")

    # ------------------------------------------------------------------
    # Internal — retry loop
    # ------------------------------------------------------------------

    async def _start_with_retry(self) -> None:
        max_retries: int = self.config.get("event_client_max_retries", -1)
        delay: float = float(self.config.get("event_client_retry_delay", 5.0))
        attempt = 0
        while True:
            try:
                await self._connect_and_subscribe()
                self._subscriptions_ready = True
                logger.info("NATSClient connected and subscribed successfully")
                return
            except Exception as e:
                attempt += 1
                self._subscriptions_ready = False
                if max_retries != -1 and attempt > max_retries:
                    raise
                logger.warning("NATSClient attempt %d failed, retrying in %.1fs: %s", attempt, delay, e)
                await asyncio.sleep(delay)

    def _on_retry_done(self, task: asyncio.Task[None]) -> None:
        """Report a retry task that gave up, naming the agent whose transport it was (C7).

        The agent is in the message because this is the one record that a namespace has
        stopped consuming while the pod stays healthy: the task is detached, so nothing
        awaits it, and without this the failure is a task exception nobody retrieves.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Agent '%s' permanently failed to connect to NATS after exhausting retries: %s",
                self.namespace or ROOT_LABEL,
                exc,
                exc_info=exc,
            )

    async def _connect_and_subscribe(self) -> None:
        await self.connect()
        # Clean up any partial subscriptions from a previous failed attempt
        for sub in self._subscriptions:
            with contextlib.suppress(Exception):
                await sub.unsubscribe()
        self._subscriptions.clear()
        await self._subscribe_all()

    async def _subscribe_all(self) -> None:
        """Provision the stream once, then subscribe every topic.

        Shared by first connect and by reconnect, so a stream that was recreated while the
        client was away -- or a failover to a cluster peer that never had it -- is restored
        before any consumer tries to bind to it.
        """
        if self._use_jetstream:
            await self._provision_stream()
        for topic, callback in self._topic_callbacks.items():
            await self._subscribe_one(topic, callback)

    # ------------------------------------------------------------------
    # Internal -- JetStream stream and consumer
    # ------------------------------------------------------------------

    def _stream_subjects(self) -> set[str]:
        """Subjects the stream must carry for this client's consumers to bind.

        Each topic is included literally, because that is what a consumer filters on. The
        previous code stored only ``f"{topic}.>"``, which does *not* cover ``topic`` itself,
        so an explicitly created consumer filtering ``orders.created`` would be rejected by
        a stream that only captured ``orders.created.>``. The wildcard form is kept as well,
        so a stream provisioned by an earlier version keeps every subject it already had.
        """
        subjects: set[str] = set()
        for topic in self._topic_callbacks:
            subjects.add(topic)
            if "*" not in topic and ">" not in topic:
                subjects.add(f"{topic}.>")
        if self._tuning and self._tuning.dead_letter_subject:
            subjects.add(self._tuning.dead_letter_subject)
        return subjects

    async def _provision_stream(self) -> None:
        """Create the stream, or widen an existing one to cover every needed subject.

        Called once per (re)connect rather than once per topic. The previous per-topic
        ``add_stream`` could only ever create the stream for whichever topic happened to be
        subscribed first: every later call hit "stream name already in use" and was logged
        as a warning, leaving the remaining topics uncaptured.

        Widening is additive -- subjects already on the stream are kept -- so this never
        removes a subject an operator added. A failure to update is logged rather than
        raised: the consumer that needs the subject fails immediately afterwards, and that
        failure names the consumer as well as the stream.
        """
        js = self._nats_client.jetstream()  # type: ignore[union-attr]
        stream = self.config.get("nats_stream_name", "EVENTS")
        wanted = self._stream_subjects()

        try:
            info = await js.stream_info(stream)
        except NotFoundError:
            await js.add_stream(name=stream, subjects=sorted(wanted))
            logger.info("Created JetStream stream '%s' with subjects %s", stream, sorted(wanted))
            return

        existing = set(info.config.subjects or [])
        missing = wanted - existing
        if not missing:
            return

        info.config.subjects = sorted(existing | missing)
        try:
            await js.update_stream(info.config)
            logger.info("Added subject(s) %s to existing JetStream stream '%s'", sorted(missing), stream)
        except Exception as exc:
            logger.error(
                "JetStream stream '%s' does not carry subject(s) %s and could not be updated (%s); "
                "consumers filtering those subjects will fail to bind",
                stream,
                sorted(missing),
                exc,
            )

    def _consumer_config(self, topic: str, durable: str) -> js_api.ConsumerConfig:
        """Build the durable consumer this client wants for one topic.

        ``deliver_subject`` is derived from the durable name rather than taken from a fresh
        inbox, because every replica must bind to the *same* one: a push consumer delivers
        to one subject, and its deliver group is the queue group on that subject. Two
        replicas generating random inboxes would create two different consumers, which is
        the fan-out P1 removed.
        """
        tuning = self._tuning or self._resolve_consumer_tuning(list(self._topic_callbacks))
        return js_api.ConsumerConfig(
            durable_name=durable,
            filter_subject=topic,
            deliver_subject=f"_DELIVER.{durable}",
            deliver_group=self._queue_group or None,
            ack_policy=js_api.AckPolicy.EXPLICIT,
            ack_wait=tuning.ack_wait,
            max_ack_pending=tuning.max_ack_pending,
            max_deliver=tuning.max_deliver,
        )

    async def _ensure_consumer(self, topic: str, durable: str) -> js_api.ConsumerConfig:
        """Return the consumer config to bind to, creating the durable if it is absent.

        An existing consumer is left exactly as it is, and the difference is reported
        instead. A durable's name, filter subject and deliver group are broker-side state
        that the stream's pending and redelivery bookkeeping hangs off; rewriting it in
        place either replays messages the consumer already handled or skips ones it never
        saw. That makes reconfiguration a migration -- delete the consumer deliberately --
        rather than something a rolling restart should do silently.

        The returned config is the server's, so replicas that start after the first one
        join the deliver group already in force rather than defining a competing one.
        """
        js = self._nats_client.jetstream()  # type: ignore[union-attr]
        stream = self.config.get("nats_stream_name", "EVENTS")
        desired = self._consumer_config(topic, durable)

        try:
            info = await js.consumer_info(stream, durable)
        except NotFoundError:
            await js.add_consumer(stream, config=desired)
            logger.info(
                "Created JetStream consumer '%s' on stream '%s': filter '%s', deliver group '%s', "
                "ack_wait %.1fs, max_ack_pending %s, max_deliver %s",
                durable,
                stream,
                topic,
                desired.deliver_group,
                desired.ack_wait,
                desired.max_ack_pending,
                desired.max_deliver,
            )
            return desired

        drift = self._consumer_drift(info.config, desired)
        if drift:
            logger.warning(
                "JetStream consumer '%s' on stream '%s' already exists with different settings (%s). "
                "It is left unchanged: changing a durable's filter or deliver group is a migration, "
                "not a restart. Delete the consumer during a maintenance window to apply the new values.",
                durable,
                stream,
                "; ".join(drift),
            )
        return info.config

    @staticmethod
    def _consumer_drift(actual: js_api.ConsumerConfig, desired: js_api.ConsumerConfig) -> list[str]:
        """Name the settings on which an existing consumer differs from the wanted one."""
        return [
            f"{field}: broker has {getattr(actual, field)!r}, config asks for {getattr(desired, field)!r}"
            for field in ("filter_subject", "deliver_group", "ack_wait", "max_ack_pending", "max_deliver")
            if getattr(actual, field) != getattr(desired, field)
        ]

    # ------------------------------------------------------------------
    # Internal — per-topic subscription
    # ------------------------------------------------------------------

    async def _subscribe_one(self, topic: str, callback: Callable[[CloudEvent[Any]], Awaitable[None]]) -> None:
        client = await self.client

        async def message_handler(msg: Any) -> None:
            self._enter_handler()
            try:
                cloud_event = self._decode_message(msg, topic)
                if cloud_event is None:
                    # A payload that will not parse now will not parse on redelivery either.
                    await self._settle(msg, DeliveryDisposition.TERM, topic, None)
                    return

                try:
                    await callback(cloud_event)
                except Exception as ex:
                    disposition = disposition_for(ex)
                    logger.error(
                        "Handler failed for event %s on topic '%s', will %s: %s",
                        cloud_event.id,
                        topic,
                        disposition.value,
                        ex,
                        exc_info=True,
                    )
                    await self._settle(msg, disposition, topic, cloud_event.id)
                else:
                    await self._settle(msg, DeliveryDisposition.ACK, topic, cloud_event.id)
            finally:
                self._exit_handler()

        try:
            if self._use_jetstream and client.jetstream():
                stream_name = self.config.get("nats_stream_name", "EVENTS")
                durable_name = self._durables.get(topic) or self._durable_for(topic)

                # subscribe_bind rather than subscribe, because the queue group cannot reach a
                # durable any other way: nats-py rejects a queue subscription whose durable name
                # differs from the queue name, and the durable is per topic while the queue group
                # is per agent. Binding to a consumer we create ourselves also puts ack_wait,
                # max_ack_pending and max_deliver where the broker can enforce them.
                consumer_config = await self._ensure_consumer(topic, durable_name)
                sub = await client.jetstream().subscribe_bind(
                    stream=stream_name,
                    config=consumer_config,
                    consumer=durable_name,
                    cb=message_handler,
                    manual_ack=True,
                )
                logger.info(
                    "Subscribed to JetStream topic '%s' via durable '%s' in deliver group '%s'",
                    topic,
                    durable_name,
                    consumer_config.deliver_group or "<none>",
                )
            else:
                sub = await client.subscribe(topic, queue=self._queue_group, cb=message_handler)
                logger.info("Subscribed to Core NATS topic '%s' in queue group '%s'", topic, self._queue_group)

            self._subscriptions.append(sub)

        except Exception as e:
            logger.error("Failed to subscribe to topic '%s': %s", topic, str(e))
            raise

    # ------------------------------------------------------------------
    # Internal — acknowledgement
    # ------------------------------------------------------------------

    async def _settle(self, msg: Any, disposition: DeliveryDisposition, topic: str, event_id: str | None) -> None:
        """Tell the broker what became of a delivery (spec sec. 7.2).

        Only JetStream deliveries can be settled. Core NATS is fire-and-forget and
        ``msg.ack()`` raises ``NotJSMessageError`` there, so the JetStream flag gates the
        whole method. It gates on ``_use_jetstream`` rather than on ``msg.reply`` because a
        Core NATS request/reply message also carries a reply subject, and publishing ``+ACK``
        to a waiting requester would be worse than not acknowledging at all.

        A failure to settle is logged and swallowed. An acknowledgement is published to the
        delivering connection's reply subject, so it fails precisely when that connection is
        gone -- raising into the ``nats-py`` callback would neither deliver it nor recover it.
        The message is redelivered after ``ack_wait`` instead, which is the at-least-once
        behaviour sec. 7.4 already requires handlers to tolerate.

        A nak on the delivery the broker will not repeat is turned into a dead letter and a
        term. Naking there would be a lie: ``max_deliver`` is already reached, so nothing
        redelivers and the message leaves the consumer with no trace of why. Terming it here
        keeps the payload, on the dead-letter subject, and releases the consumer's pending
        slot immediately instead of one more ``ack_wait`` later.
        """
        if not self._use_jetstream:
            return

        try:
            if disposition is DeliveryDisposition.ACK:
                await msg.ack()
            elif disposition is DeliveryDisposition.NAK and not self._deliveries_exhausted(msg):
                await msg.nak()
            else:
                await self._dead_letter(msg, disposition, topic, event_id)
                await msg.term()
        except Exception as exc:
            logger.error(
                "Could not %s event %s on topic '%s' (%s); it will be redelivered after ack_wait",
                disposition.value,
                event_id or "<undecodable>",
                topic,
                exc,
            )

    def _deliveries_exhausted(self, msg: Any) -> bool:
        """Whether the broker has no redelivery left for this message.

        ``max_deliver`` counts attempts, so the last one the broker makes is attempt
        ``max_deliver`` itself: naking *that* delivery buys nothing. ``-1`` means unlimited
        and is never exhausted. A message whose JetStream metadata cannot be read is treated
        as not exhausted, so an unreadable header can only cost a retry, never a payload.
        """
        max_deliver = self._tuning.max_deliver if self._tuning else -1
        if max_deliver < 0:
            return False
        delivered = self._delivery_count(msg)
        return delivered is not None and delivered >= max_deliver

    @staticmethod
    def _delivery_count(msg: Any) -> int | None:
        """Number of times the broker has delivered this message, or ``None`` if unknown."""
        try:
            return int(msg.metadata.num_delivered)
        except Exception:
            return None

    async def _dead_letter(self, msg: Any, disposition: DeliveryDisposition, topic: str, event_id: str | None) -> None:
        """Republish a message the framework has given up on, before the delivery is termed.

        Both terminal outcomes arrive here: a payload rejected as unprocessable, and one
        whose redeliveries are spent. This is the last point at which the payload still
        exists -- the ``term()`` that follows removes it from the consumer -- so the original
        bytes are republished unchanged, including a payload that never parsed as a
        CloudEvent. What went wrong travels in headers instead, where it cannot corrupt a
        body a dead-letter consumer will try to read.
        """
        subject = self._tuning.dead_letter_subject if self._tuning else ""
        delivered = self._delivery_count(msg)
        reason = "deliveries-exhausted" if disposition is DeliveryDisposition.NAK else "terminal-failure"

        if not subject:
            self._count_dead_letter(reason, kept=False)
            logger.warning(
                "Dropping event %s from topic '%s' after %s delivery attempt(s) (%s): no dead-letter "
                "subject is configured, so its payload is lost. Set 'nats_dead_letter_subject' to keep it.",
                event_id or "<undecodable>",
                topic,
                delivered if delivered is not None else "an unknown number of",
                reason,
            )
            return

        headers = {
            "Blueprint-Dead-Letter-Reason": reason,
            "Blueprint-Original-Subject": topic,
            "Blueprint-Delivery-Count": str(delivered) if delivered is not None else "unknown",
        }
        if event_id:
            headers["Blueprint-Event-Id"] = event_id

        try:
            await self._nats_client.jetstream().publish(subject, msg.data, headers=headers)  # type: ignore[union-attr]
        except Exception as exc:
            self._count_dead_letter(reason, kept=False)
            logger.error(
                "Could not move event %s from topic '%s' to dead-letter subject '%s' (%s); its payload is lost",
                event_id or "<undecodable>",
                topic,
                subject,
                exc,
            )
            return

        self._count_dead_letter(reason, kept=True)
        logger.warning(
            "Moved event %s from topic '%s' to dead-letter subject '%s' after %s delivery attempt(s) (%s)",
            event_id or "<undecodable>",
            topic,
            subject,
            delivered if delivered is not None else "an unknown number of",
            reason,
        )

    def _count_dead_letter(self, reason: str, *, kept: bool) -> None:
        """Record one event this agent gave up on.

        Counted once per event, where the outcome is known, rather than once on entry: a
        publish that fails has still lost the payload, and counting on entry and again on
        failure would report two dead letters for one message.

        Args:
            reason: ``deliveries-exhausted`` or ``terminal-failure``.
            kept: Whether the payload reached the dead-letter subject. ``False`` is what tells a
                deployment with no subject configured that it is losing them.
        """
        self._dead_lettered.add(1, {"agent": self.namespace or ROOT_LABEL, "reason": reason, "kept": kept})

    # ------------------------------------------------------------------
    # Internal — reconnect callbacks
    # ------------------------------------------------------------------

    async def _on_disconnected(self) -> None:
        self._subscriptions_ready = False
        logger.warning("NATSClient disconnected")

    async def _on_reconnected(self) -> None:
        logger.info("NATSClient reconnected")
        if not self._subscriptions_managed:
            return
        if self._consumption_paused:
            # A reconnect must not undo a pause. Without this the broker dropping and
            # restoring the connection would silently resubscribe a degraded agent, and C4
            # would hold only until the next network blip.
            logger.info("Agent '%s' stays paused after the reconnect; it is still degraded", self.namespace or ROOT_LABEL)
            return
        if self._use_jetstream and self._topic_callbacks:
            # JetStream durable consumers do not survive reconnects; re-subscribe manually.
            # Core NATS re-subscribes automatically via the client library.
            self._subscriptions.clear()
            try:
                await self._subscribe_all()
            except Exception as e:
                logger.error("NATSClient failed to re-establish JetStream subscriptions after reconnect: %s", e)
                return
        self._subscriptions_ready = True
        logger.info("NATSClient subscriptions ready after reconnect")
