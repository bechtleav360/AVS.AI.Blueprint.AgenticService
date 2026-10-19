"""Unified processing service that coordinates handlers and runtimes."""

import asyncio
import logging
from typing import Any
from uuid import uuid4
from pydantic import ValidationError

from opentelemetry import trace
from ...component.component import traced
from ...component.namespace import ROOT_LABEL, ROOT_NAMESPACE, namespace_of
from ...handler.handler_chain import RUNTIME_NAME_CONTEXT_KEY, HandlerChain
from ...io.telemetry.inflight import IN_FLIGHT
from ...models import ProcessingResult, ProcessingStatus
from ...models.errors import describe_validation_errors
from ...models.events import GenericCloudEvent, HandlerResult, CloudEvent
from ..service_base import ServiceBase
from .event_publishing_service import EventPublishingService

logger = logging.getLogger(__name__)


def _cancellation_requested() -> bool:
    """Report whether the current task has been asked to cancel and has not withdrawn the request.

    How a run that swallowed its cancellation is told apart from one that finished in time: the
    handler returned normally, but ``asyncio.timeout`` (``nats_handler_timeout``) or a shutdown
    has cancelled the task, and the transport edge will nak or abandon the delivery rather than
    acknowledge it. Erring this way is safe -- a delivery acknowledged anyway merely loses its
    marker early, which is at-least-once, never a lost event.
    """
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


class EventProcessingService(ServiceBase):
    """Unified service for processing requests through handlers and runtimes.

    This service provides a consistent interface for all API endpoints
    (REST, Events, Dapr) to process requests using the registered handlers
    and agent runtimes.

    One service, one chain per agent
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    There is a single instance of this service in a process, at the root, because what it does
    -- correlation context, request ids, unwrapping, normalising handler output -- is the same
    for every agent. What is *not* the same is the dispatch: which handlers an event is offered
    to, which dedup policy applies, and which cache partition the markers go in. All three are
    properties of a :class:`HandlerChain`, so the service keeps one chain per namespace and
    every caller says which agent it is dispatching for.

    A caller that says nothing gets the root chain, which in a single-agent application is
    every handler in the process.
    """

    def __init__(self) -> None:
        super().__init__()
        # The root chain always exists, so an application that never mentions a namespace --
        # every application that exists today -- behaves exactly as it did.
        self._handler_chains: dict[str, HandlerChain] = {ROOT_NAMESPACE: HandlerChain()}
        self._correlation_context = self.registry.correlation_context

    async def on_startup(self) -> None:
        """Start one handler chain per namespace that has handlers registered in it.

        The chains are not registered components, so nothing else calls their lifecycle hooks.
        A chain's startup resolves its idempotency policy, and that has to happen while the
        application is starting: a misconfigured dedup window must fail the pod, not the first
        event that arrives on it.

        That guarantee is per agent, which is why the chains are built here rather than on first
        delivery. Otherwise a group whose second agent has a bad ``idempotency_ttl`` would start
        cleanly and fail on an event hours later, and the first agent's clean startup would have
        said nothing about it.

        The namespaces come from the registered handlers, not from any list of agents. The
        registry deliberately cannot enumerate agents (C6) and this service is not the builder;
        what it needs is not "which agents exist" but "which namespaces have handlers to
        dispatch to", and the handlers themselves are the authority on that.
        """
        for namespace in sorted({namespace_of(handler) for handler in self.registry.get_event_handler()}):
            self._chain_for(namespace)

        for namespace, chain in self._handler_chains.items():
            await chain.on_startup()
            logger.debug("Handler chain for namespace '%s' started", namespace or ROOT_LABEL)

    async def on_shutdown(self) -> None:
        """Stop every handler chain, for the same reason startup starts them."""
        for chain in self._handler_chains.values():
            await chain.on_shutdown()

    def _chain_for(self, namespace: str) -> HandlerChain:
        """Return the chain for ``namespace``, creating it if there is not one yet.

        Creation is lazy for a namespace that had no handler at startup. A chain is cheap, and
        raising here would turn a handler registered after startup into a failed delivery
        instead of a dispatch that finds nobody -- which is the outcome the acknowledgement
        contract already has a disposition for. A chain created this way resolves its own dedup
        policy on first use, which ``HandlerChain.process`` already does for exactly this case.
        """
        chain = self._handler_chains.get(namespace)
        if chain is None:
            chain = HandlerChain(namespace=namespace)
            self._handler_chains[namespace] = chain
            logger.debug("Created a handler chain for namespace '%s'", namespace or ROOT_LABEL)
        return chain

    @traced("event")
    async def process_event(
        self,
        event: GenericCloudEvent,
        context: dict[str, Any] | None = None,
        runtime_name: str | None = None,
        new_subject: str | None = None,
        *,
        namespace: str = ROOT_NAMESPACE,
    ) -> ProcessingResult:
        """Process a CloudEvent through one agent's handler chain.

        Args:
            event: The CloudEvent to process
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default
            new_subject: New subject for the CloudEvent
            namespace: The agent this delivery belongs to. Keyword-only, because the four
                parameters before it are passed positionally by existing callers. ``""`` is the
                root, which is what every caller that does not know about agents gets.

        Returns:
            ProcessingResult describing the processing outcome
        """
        if context is None:
            context = {}

        # The caller's id if it has one. The REST path creates one, logs it and returns it as the
        # RFC 7807 traceId; overwriting it here gave processing a second id that matched nothing
        # the caller could see.
        request_id = str(context.get("request_id") or uuid4())
        context["request_id"] = request_id
        span = trace.get_current_span()
        span.set_attribute("request_id", request_id)
        # The agent goes on the span as well as in the log line. A span that is still open when
        # the process dies never reaches an exporter, so the resource that would have named its
        # agent (C2) is never applied -- what is on the span itself is all a post-mortem has.
        span.set_attribute("agent", namespace or ROOT_LABEL)

        # The caller's choice of runtime, put where the chain will look for it. This
        # parameter has existed since before there were agents to resolve and was only ever
        # logged; the chain now treats it as a default, below the winning handler's own
        # get_runtime_name() and above the single-runtime fallback. Only set when asked for,
        # so a caller that passes nothing leaves the key absent rather than None -- which is
        # the difference between "no preference" and "explicitly no runtime".
        if runtime_name:
            context[RUNTIME_NAME_CONTEXT_KEY] = runtime_name

        correlation_token = self._correlation_context.set(getattr(event, "id", None) or request_id)

        logger.info(
            "Starting event processing for request %s",
            request_id,
            extra={
                "request_id": request_id,
                "event_type": event.type,
                "event_source": event.source,
                "event_id": getattr(event, "id", None),
                "runtime_name": runtime_name,
                "agent": namespace or ROOT_LABEL,
            },
        )

        event = self._unwrap_dapr_event(event)

        chain = self._chain_for(namespace)
        # The dedup bracket: from the chain's claim to a settled result. Only a delivery that
        # gets to the end keeps its marker; every other exit gives it back (chain.release is a
        # no-op unless this delivery holds a claim). A finally with a flag rather than an except
        # clause, because the exits that lost events were not Exceptions: a handler timeout or a
        # shutdown cancels the run, and a handler that swallows that cancellation returns
        # normally although the edge naks it.
        settled = False
        try:
            # Counted around the chain, not around the transport: this is the one place both
            # transports and the REST path pass through, so one measurement covers all three
            # and it means "work this agent is doing" rather than "messages it has taken".
            with IN_FLIGHT.track(namespace):
                handler_result: Any | HandlerResult | list[HandlerResult] | None = await chain.process(event, context)

            handler_results: list[HandlerResult] = self._extract_handler_results(handler_result)

            for index, result in enumerate(handler_results):
                if result.event_type:
                    # This agent's publishing service, falling back to a root one. Not the
                    # unscoped lookup this used to be: with one publishing service per
                    # namespace (P6) that finds several and refuses to choose, so a grouped
                    # process would fail on the first handler that returns an event_type.
                    publisher = self.registry.get_component(EventPublishingService, namespace=namespace)
                    await publisher.publish_handler_event(
                        event_type=result.event_type,
                        data=result.data,
                        metadata=result.metadata or {},
                        source_event=event,
                        new_subject=result.subject or new_subject,
                        index=index,
                    )

            if handler_result is None:
                status = ProcessingStatus.NO_HANDLER_FOUND
            elif handler_results and all(result.is_skipped for result in handler_results):
                # Only a run whose every result is a skip counts as skipped: a list that mixes a
                # skip with real results did work, and its skips simply publish nothing.
                status = ProcessingStatus.SKIPPED
            else:
                status = ProcessingStatus.PROCESSED
            processing_result = self._build_result(request_id, handler_results, status)
            settled = not _cancellation_requested()
            return processing_result

        # A failure propagates unlogged: every caller is a transport edge (NATS, Dapr, REST) that
        # logs it with what it decided to do about it. Logging here too duplicated each failure.
        finally:
            if not settled:
                await chain.release(event, context)
            self._correlation_context.reset(correlation_token)

    async def process_rest_request(
        self,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
        runtime_name: str | None = None,
        *,
        namespace: str = ROOT_NAMESPACE,
    ) -> ProcessingResult:
        """Process a REST request by converting it to a CloudEvent and processing.

        Args:
            payload: The REST request payload
            context: Additional context for processing
            runtime_name: Specific runtime to use, or None for default
            namespace: The agent whose REST API received the request, so the synthesised event
                is dispatched to that agent's handlers and no other's.

        Returns:
            ProcessingResult describing the processing outcome
        """
        event = GenericCloudEvent(
            specversion="1.0",
            datacontenttype="application/json",
            dataschema=None,
            data_base64=None,
            id=str(uuid4()),
            source="/api/rest",
            type="rest.request",
            data=payload,
            subject="rest.request",
        )
        return await self.process_event(event, context, runtime_name, namespace=namespace)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_handler_results(handler_result: Any) -> list[HandlerResult]:
        """Normalize handler output to a list of HandlerResult objects."""

        def _to_handler_result(value: Any) -> HandlerResult:
            if isinstance(value, HandlerResult):
                return value
            if isinstance(value, dict):
                event_type = value.get("event_type") or None
                raw_metadata = value.get("metadata")
                metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                data = value.get("data")
                if not isinstance(data, dict):
                    if event_type is None and not metadata:
                        data = value
                    else:
                        data = {"value": data}
                return HandlerResult(event_type=event_type, data=data, metadata=metadata)
            return HandlerResult(event_type=None, data=value, metadata={})

        if handler_result is None:
            return []
        if isinstance(handler_result, list):
            return [_to_handler_result(item) for item in handler_result]
        return [_to_handler_result(handler_result)]

    @staticmethod
    def _build_result(
        request_id: str,
        handler_results: list[HandlerResult],
        status: ProcessingStatus,
    ) -> ProcessingResult:
        """Build a ProcessingResult from handler outputs."""
        if status == ProcessingStatus.NO_HANDLER_FOUND:
            message = "No handler processed this event"
        elif status == ProcessingStatus.SKIPPED:
            message = "Skipped: " + "; ".join(result.skip_reason or "" for result in handler_results)
        else:
            message = "Message acknowledged"
        return ProcessingResult(
            request_id=request_id,
            status=status,
            result=handler_results,
            metadata={},
            message=message,
        )

    def _unwrap_dapr_event(self, event: GenericCloudEvent) -> GenericCloudEvent:
        """Unwrap Dapr-wrapped events (com.dapr.event.sent envelope).

        A malformed inner event raises and is not logged here: the transport edge logs the
        failure with its traceback. The errors therefore carry no payload value, and a
        validation failure is raised ``from None`` -- its pydantic cause would print every
        offending input in that traceback (B2).
        """
        if event.type != "com.dapr.event.sent":
            return event

        logger.warning(
            "Event from topic %s is of type 'com.dapr.event.sent', unwrapping inner event.",
            getattr(event, "topic", "unknown"),
        )
        inner_event = event.data

        if isinstance(inner_event, CloudEvent):
            return inner_event

        if isinstance(inner_event, dict):
            if "type" not in inner_event:
                raise RuntimeError("Inner Dapr event is missing required 'type' field")
            try:
                return GenericCloudEvent.model_validate(inner_event)
            except ValidationError as exc:
                raise RuntimeError(
                    f"Inner Dapr event could not be parsed as CloudEvent: {describe_validation_errors(exc.errors())}"
                ) from None

        raise RuntimeError(f"Unsupported inner Dapr event payload type: {type(inner_event).__name__}")
