"""Unit tests for EventHandlingBase._unwrap_nested_cloud_event and handle_event."""

import json
from unittest.mock import AsyncMock, MagicMock

from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.models.result import ProcessingResult

# ---------------------------------------------------------------------------
# _unwrap_nested_cloud_event
# ---------------------------------------------------------------------------


class TestUnwrapNestedCloudEvent:
    def test_non_dapr_event_is_returned_as_is(self, dapr_eventing: DaprEventing) -> None:
        event = CloudEvent(id="e1", type="custom.event", source="src")
        result, was_unwrapped = dapr_eventing._unwrap_nested_cloud_event(event)
        assert result is event
        assert was_unwrapped is False

    def test_dapr_envelope_with_dict_payload_is_unwrapped(self, dapr_eventing: DaprEventing) -> None:
        inner = {
            "specversion": "1.0",
            "id": "inner-id",
            "source": "inner-src",
            "type": "inner.type",
        }
        envelope = CloudEvent(
            id="env-id",
            type="com.dapr.event.sent",
            source="dapr",
            data=inner,
        )
        result, was_unwrapped = dapr_eventing._unwrap_nested_cloud_event(envelope)
        assert was_unwrapped is True
        assert result.id == "inner-id"
        assert result.type == "inner.type"

    def test_dapr_envelope_with_json_string_payload_is_unwrapped(self, dapr_eventing: DaprEventing) -> None:
        inner = {
            "specversion": "1.0",
            "id": "str-inner-id",
            "source": "src",
            "type": "str.event",
        }
        envelope = CloudEvent(
            id="env-id",
            type="com.dapr.event.sent",
            source="dapr",
            data=json.dumps(inner),
        )
        result, was_unwrapped = dapr_eventing._unwrap_nested_cloud_event(envelope)
        assert was_unwrapped is True
        assert result.id == "str-inner-id"

    def test_dapr_envelope_with_malformed_json_string_is_not_unwrapped(self, dapr_eventing: DaprEventing) -> None:
        envelope = CloudEvent(
            id="env-id",
            type="com.dapr.event.sent",
            source="dapr",
            data="{not valid json}",
        )
        result, was_unwrapped = dapr_eventing._unwrap_nested_cloud_event(envelope)
        assert was_unwrapped is False
        assert result is envelope

    def test_dapr_envelope_with_missing_required_fields_is_not_unwrapped(self, dapr_eventing: DaprEventing) -> None:
        incomplete_inner = {"id": "e1", "source": "src"}  # missing specversion and type
        envelope = CloudEvent(
            id="env-id",
            type="com.dapr.event.sent",
            source="dapr",
            data=incomplete_inner,
        )
        result, was_unwrapped = dapr_eventing._unwrap_nested_cloud_event(envelope)
        assert was_unwrapped is False
        assert result is envelope

    def test_dapr_envelope_with_none_data_is_not_unwrapped(self, dapr_eventing: DaprEventing) -> None:
        envelope = CloudEvent(id="env-id", type="com.dapr.event.sent", source="dapr")
        result, was_unwrapped = dapr_eventing._unwrap_nested_cloud_event(envelope)
        assert was_unwrapped is False
        assert result is envelope


# ---------------------------------------------------------------------------
# handle_event
# ---------------------------------------------------------------------------


class TestHandleEvent:
    async def test_processed_status_returns_success(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        processed_result: ProcessingResult,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(return_value=processed_result)
        mock_registry.correlation_context.set.return_value = MagicMock()

        result = await dapr_eventing.handle_event("topic", cloud_event)
        assert result["status"] == "SUCCESS"

    async def test_non_processed_status_returns_retry(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(return_value=unhandled_result)
        mock_registry.correlation_context.set.return_value = MagicMock()

        result = await dapr_eventing.handle_event("topic", cloud_event)
        assert result["status"] == "RETRY"

    async def test_retry_result_includes_reason(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(return_value=unhandled_result)
        mock_registry.correlation_context.set.return_value = MagicMock()

        result = await dapr_eventing.handle_event("topic", cloud_event)
        assert "reason" in result
