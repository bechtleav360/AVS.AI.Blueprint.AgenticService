"""A delivery continues the trace its CloudEvent was published under (``traceparent``/``tracestate``)."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from blueprint.agents.io.api.eventing.cloud_event_processor_mixin import producer_trace_context
from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.models.result import ProcessingResult

_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
_SPAN_ID = "00f067aa0ba902b7"
_TRACEPARENT = f"00-{_TRACE_ID}-{_SPAN_ID}-01"
_ENVELOPE_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
_ENVELOPE_TRACEPARENT = f"00-{_ENVELOPE_TRACE_ID}-b7ad6b7169203331-01"


def _current_trace_id() -> str:
    return format(trace.get_current_span().get_span_context().trace_id, "032x")


def _event(**extensions: Any) -> CloudEvent:
    return CloudEvent(id="evt-1", type="orders.created", source="backend", **extensions)


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def tracer(exporter: InMemorySpanExporter) -> trace.Tracer:
    """A tracer of its own: the global provider stays as the other tests left it."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(__name__)


@pytest.fixture
def seen(dapr_eventing: DaprEventing, processed_result: ProcessingResult, tracer: trace.Tracer) -> Iterator[list[str]]:
    """The trace id current while the processing service ran, one entry per dispatch.

    The stand-in opens a span as ``process_event``'s ``@traced`` does, so the tests can check what
    that span's parent is.
    """
    trace_ids: list[str] = []

    async def process_event(*_: Any, **__: Any) -> ProcessingResult:
        with tracer.start_as_current_span("process_event"):
            trace_ids.append(_current_trace_id())
        return processed_result

    processing_service = MagicMock()
    processing_service.process_event = AsyncMock(side_effect=process_event)
    dapr_eventing.registry.get_service.return_value = processing_service  # type: ignore[attr-defined]
    yield trace_ids


class TestTheDeliveryContinuesTheProducersTrace:
    async def test_processing_runs_in_the_trace_of_the_event(self, dapr_eventing: DaprEventing, seen: list[str]) -> None:
        await dapr_eventing._dispatch_cloud_event(_event(traceparent=_TRACEPARENT), {})

        assert seen == [_TRACE_ID]

    async def test_the_first_span_is_a_child_of_the_producers_span(
        self, dapr_eventing: DaprEventing, seen: list[str], exporter: InMemorySpanExporter
    ) -> None:
        await dapr_eventing._dispatch_cloud_event(_event(traceparent=_TRACEPARENT), {})

        (span,) = exporter.get_finished_spans()
        assert span.parent is not None
        assert format(span.parent.span_id, "016x") == _SPAN_ID
        assert span.parent.is_remote

    async def test_tracestate_travels_with_it(self, dapr_eventing: DaprEventing, seen: list[str], exporter: InMemorySpanExporter) -> None:
        await dapr_eventing._dispatch_cloud_event(_event(traceparent=_TRACEPARENT, tracestate="vendor=value"), {})

        (span,) = exporter.get_finished_spans()
        assert span.context.trace_state.get("vendor") == "value"

    async def test_the_previous_context_is_current_again_afterwards(self, dapr_eventing: DaprEventing, seen: list[str]) -> None:
        before = _current_trace_id()

        await dapr_eventing._dispatch_cloud_event(_event(traceparent=_TRACEPARENT), {})

        assert _current_trace_id() == before

    async def test_the_previous_context_is_current_again_when_processing_fails(self, dapr_eventing: DaprEventing) -> None:
        processing_service = MagicMock()
        processing_service.process_event = AsyncMock(side_effect=RuntimeError("boom"))
        dapr_eventing.registry.get_service.return_value = processing_service  # type: ignore[attr-defined]
        before = _current_trace_id()

        with pytest.raises(RuntimeError, match="boom"):
            await dapr_eventing._dispatch_cloud_event(_event(traceparent=_TRACEPARENT), {})

        assert _current_trace_id() == before

    @pytest.mark.parametrize(
        "extensions",
        [{}, {"tracestate": "vendor=value"}, {"traceparent": ""}, {"traceparent": 7}, {"traceparent": "not-a-traceparent"}],
        ids=["none", "tracestate only", "empty traceparent", "not a string", "malformed"],
    )
    async def test_an_event_without_a_usable_traceparent_starts_a_trace_of_its_own(
        self, dapr_eventing: DaprEventing, seen: list[str], exporter: InMemorySpanExporter, extensions: dict[str, Any]
    ) -> None:
        await dapr_eventing._dispatch_cloud_event(_event(**extensions), {})

        (span,) = exporter.get_finished_spans()
        assert span.parent is None

    async def test_a_caller_that_traces_the_delivery_keeps_its_own_span_as_parent(
        self, dapr_eventing: DaprEventing, seen: list[str], tracer: trace.Tracer, exporter: InMemorySpanExporter
    ) -> None:
        with tracer.start_as_current_span("caller") as caller:
            await dapr_eventing._dispatch_cloud_event(_event(traceparent=_TRACEPARENT), {})

        processing = next(span for span in exporter.get_finished_spans() if span.name == "process_event")
        assert processing.parent is not None
        assert processing.parent.span_id == caller.get_span_context().span_id
        assert seen != [_TRACE_ID]


class TestDaprEnvelopes:
    @staticmethod
    def _envelope(inner: dict[str, Any], **extensions: Any) -> CloudEvent:
        return CloudEvent(id="env-1", type="com.dapr.event.sent", source="dapr", data=inner, **extensions)

    async def test_the_delivered_events_trace_wins_over_the_envelopes(self, dapr_eventing: DaprEventing, seen: list[str]) -> None:
        inner = {"specversion": "1.0", "id": "evt-1", "source": "backend", "type": "orders.created", "traceparent": _TRACEPARENT}

        await dapr_eventing._dispatch_cloud_event(self._envelope(inner, traceparent=_ENVELOPE_TRACEPARENT), {})

        assert seen == [_TRACE_ID]

    async def test_the_envelopes_trace_is_used_when_the_event_has_none(self, dapr_eventing: DaprEventing, seen: list[str]) -> None:
        inner = {"specversion": "1.0", "id": "evt-1", "source": "backend", "type": "orders.created"}

        await dapr_eventing._dispatch_cloud_event(self._envelope(inner, traceparent=_ENVELOPE_TRACEPARENT), {})

        assert seen == [_ENVELOPE_TRACE_ID]


class TestProducerTraceContext:
    def test_no_event_no_context(self) -> None:
        assert producer_trace_context() is None

    def test_the_first_usable_event_is_taken(self) -> None:
        producer = producer_trace_context(_event(traceparent=""), _event(traceparent=_TRACEPARENT))

        assert producer is not None
        assert format(trace.get_current_span(producer).get_span_context().trace_id, "032x") == _TRACE_ID
