"""Unit tests for EventProcessingService."""

from unittest.mock import AsyncMock

import pytest

from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
from blueprint.agents.models.result import ProcessingStatus
from blueprint.agents.services.eventing.event_processing_service import EventProcessingService

# ---------------------------------------------------------------------------
# _extract_handler_results (static — no instance needed)
# ---------------------------------------------------------------------------


class TestExtractHandlerResults:
    def test_none_returns_empty_list(self) -> None:
        assert EventProcessingService._extract_handler_results(None) == []

    def test_single_handler_result_wrapped_in_list(self) -> None:
        hr = HandlerResult(event_type="a", data={"x": 1})
        result = EventProcessingService._extract_handler_results(hr)
        assert result == [hr]

    def test_list_of_handler_results_returned_unchanged(self) -> None:
        hr1 = HandlerResult(event_type="a")
        hr2 = HandlerResult(event_type="b")
        result = EventProcessingService._extract_handler_results([hr1, hr2])
        assert result == [hr1, hr2]

    def test_dict_with_event_type_and_dict_data(self) -> None:
        raw = {"event_type": "foo", "data": {"key": "val"}}
        result = EventProcessingService._extract_handler_results(raw)
        assert len(result) == 1
        assert result[0].event_type == "foo"
        assert result[0].data == {"key": "val"}

    def test_dict_with_event_type_and_non_dict_data_wraps_in_value(self) -> None:
        raw = {"event_type": "foo", "data": "plain-string"}
        result = EventProcessingService._extract_handler_results(raw)
        assert result[0].data == {"value": "plain-string"}

    def test_bare_dict_without_event_type_becomes_data_itself(self) -> None:
        """Dict with no 'event_type' and no 'metadata' key: the whole dict is used as data."""
        raw = {"key": "val"}
        result = EventProcessingService._extract_handler_results(raw)
        assert len(result) == 1
        assert result[0].event_type is None
        assert result[0].data == {"key": "val"}


# ---------------------------------------------------------------------------
# _build_result (static — no instance needed)
# ---------------------------------------------------------------------------


class TestBuildResult:
    def test_processed_status_message(self) -> None:
        result = EventProcessingService._build_result("req-1", [], ProcessingStatus.PROCESSED)
        assert result.message == "Message acknowledged"

    def test_no_handler_found_message(self) -> None:
        result = EventProcessingService._build_result("req-2", [], ProcessingStatus.NO_HANDLER_FOUND)
        assert result.message == "No handler processed this event"

    def test_result_contains_request_id(self) -> None:
        result = EventProcessingService._build_result("req-42", [], ProcessingStatus.PROCESSED)
        assert result.request_id == "req-42"

    def test_result_contains_handler_results(self) -> None:
        hr = HandlerResult(event_type="e", data={})
        result = EventProcessingService._build_result("req-1", [hr], ProcessingStatus.PROCESSED)
        assert result.result == [hr]


# ---------------------------------------------------------------------------
# _unwrap_dapr_event (instance method — uses event_processing_service fixture)
# ---------------------------------------------------------------------------


class TestUnwrapDaprEvent:
    def test_non_dapr_event_returned_unchanged(self, event_processing_service: EventProcessingService) -> None:
        event = GenericCloudEvent(id="1", type="some.event", source="src")
        assert event_processing_service._unwrap_dapr_event(event) is event

    def test_dapr_event_with_cloud_event_inner_returns_inner(self, event_processing_service: EventProcessingService) -> None:
        inner = GenericCloudEvent(id="inner-1", type="real.event", source="inner-src")
        outer = GenericCloudEvent.model_construct(id="outer-1", type="com.dapr.event.sent", source="dapr", data=inner)
        assert event_processing_service._unwrap_dapr_event(outer) is inner

    def test_dapr_event_with_dict_inner_parses_new_cloud_event(self, event_processing_service: EventProcessingService) -> None:
        outer = GenericCloudEvent(
            id="outer-1",
            type="com.dapr.event.sent",
            source="dapr",
            data={"id": "inner-1", "type": "real.event", "source": "inner-src"},
        )
        result = event_processing_service._unwrap_dapr_event(outer)
        assert result.type == "real.event"

    def test_dapr_event_dict_missing_type_raises(self, event_processing_service: EventProcessingService) -> None:
        outer = GenericCloudEvent(
            id="outer-1",
            type="com.dapr.event.sent",
            source="dapr",
            data={"id": "inner-1"},
        )
        with pytest.raises(RuntimeError, match="missing required 'type' field"):
            event_processing_service._unwrap_dapr_event(outer)

    def test_dapr_event_with_non_dict_non_event_inner_raises(self, event_processing_service: EventProcessingService) -> None:
        outer = GenericCloudEvent.model_construct(id="outer-1", type="com.dapr.event.sent", source="dapr", data=42)
        with pytest.raises(RuntimeError, match="Unsupported inner Dapr event payload type"):
            event_processing_service._unwrap_dapr_event(outer)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_is_noop(self, event_processing_service: EventProcessingService) -> None:
        await event_processing_service.on_startup()

    async def test_on_shutdown_is_noop(self, event_processing_service: EventProcessingService) -> None:
        await event_processing_service.on_shutdown()


# ---------------------------------------------------------------------------
# process_rest_request
# ---------------------------------------------------------------------------


class TestProcessRestRequest:
    async def test_delegates_to_process_event(self, event_processing_service: EventProcessingService) -> None:
        event_processing_service.process_event = AsyncMock(return_value=None)
        await event_processing_service.process_rest_request({"key": "val"})
        event_processing_service.process_event.assert_awaited_once()

    async def test_passes_payload_as_event_data(self, event_processing_service: EventProcessingService) -> None:
        captured = {}

        async def _capture(event, *args, **kwargs):
            captured["event"] = event

        event_processing_service.process_event = _capture
        await event_processing_service.process_rest_request({"answer": 42})
        assert captured["event"].data == {"answer": 42}

    async def test_event_type_is_rest_request(self, event_processing_service: EventProcessingService) -> None:
        captured = {}

        async def _capture(event, *args, **kwargs):
            captured["event"] = event

        event_processing_service.process_event = _capture
        await event_processing_service.process_rest_request({})
        assert captured["event"].type == "rest.request"
