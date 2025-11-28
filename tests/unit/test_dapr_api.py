"""Tests for Dapr API CloudEvent handling."""

import json
from unittest.mock import MagicMock, AsyncMock
import pytest

from blueprint.agents.api.dapr import DaprApi
from blueprint.agents.models.events import CloudEvent


class TestDaprApi:
    """Validate Dapr CloudEvent helper behaviour."""

    def setup_method(self) -> None:
        self.registry = MagicMock()
        self.processing_service = AsyncMock()
        self.registry.get_processing_service.return_value = self.processing_service
        self.api = DaprApi(self.registry)

    def test_unwrap_noop_when_not_dapr_event(self) -> None:
        event = CloudEvent(id="1", type="example.event", source="/example", data={"foo": "bar"})

        result_event, was_unwrapped = self.api._unwrap_nested_cloud_event(event)

        assert result_event is event
        assert was_unwrapped is False

    def test_unwrap_nested_cloudevent_from_string_payload(self) -> None:
        inner_event = {
            "specversion": "1.0",
            "id": "inner",
            "source": "connector",
            "type": "asset.discovered",
            "data": {"foo": "bar"},
        }
        event = CloudEvent(
            id="outer",
            type="com.dapr.event.sent",
            source="dapr",
            data=json.dumps(inner_event),
        )

        result_event, was_unwrapped = self.api._unwrap_nested_cloud_event(event)

        assert was_unwrapped is True
        assert result_event.id == inner_event["id"]
        assert result_event.type == inner_event["type"]
        assert result_event.data == inner_event["data"]

    def test_unwrap_nested_cloudevent_from_dict_payload(self) -> None:
        inner_event = {
            "specversion": "1.0",
            "id": "inner-dict",
            "source": "connector",
            "type": "asset.discovered",
            "data": {"foo": "baz"},
        }
        event = CloudEvent(
            id="outer",
            type="com.dapr.event.sent",
            source="dapr",
            data=inner_event,
        )

        result_event, was_unwrapped = self.api._unwrap_nested_cloud_event(event)

        assert was_unwrapped is True
        assert result_event.id == inner_event["id"]
        assert result_event.type == inner_event["type"]
        assert result_event.data == inner_event["data"]

    @pytest.mark.asyncio
    async def test_handle_dapr_event_success(self) -> None:
        """Successful processing returns SUCCESS status."""
        event = CloudEvent(id="evt-1", type="test.event", source="test", data={"foo": "bar"})

        result_event = CloudEvent(id="res-1", type="agent.output.test", source="agent", data={"status": "processed", "result": "ok"})
        self.processing_service.process_event.return_value = result_event

        response = await self.api.handle_dapr_event("test-topic", event)

        assert response == {"status": "SUCCESS"}
        self.processing_service.process_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_dapr_event_exception_returns_retry(self) -> None:
        """Exceptions during processing return RETRY status."""
        event = CloudEvent(id="evt-1", type="test.event", source="test", data={"foo": "bar"})

        self.processing_service.process_event.side_effect = ValueError("Processing failed")

        response = await self.api.handle_dapr_event("test-topic", event)

        assert response == {"status": "RETRY", "reason": "processing_failed"}

    @pytest.mark.asyncio
    async def test_handle_dapr_event_failure_status_returns_retry(self) -> None:
        """Non-success processing status returns RETRY."""
        event = CloudEvent(id="evt-1", type="test.event", source="test", data={"foo": "bar"})

        result_event = CloudEvent(id="res-1", type="agent.output.test", source="agent", data={"status": "failed", "error": "some error"})
        self.processing_service.process_event.return_value = result_event

        response = await self.api.handle_dapr_event("test-topic", event)

        assert response["status"] == "RETRY"
        assert response["reason"] == "failed"
