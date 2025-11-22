"""Tests for Dapr API CloudEvent handling."""

import json

from blueprint.agents.api.dapr import DaprApi
from blueprint.agents.models.events import CloudEvent


class _StubComponentRegistry:
    """Minimal stub that satisfies the DaprApi constructor."""

    def get_processing_service(self):  # pragma: no cover - not used in tests
        raise NotImplementedError


class TestDaprApi:
    """Validate Dapr CloudEvent helper behaviour."""

    def setup_method(self) -> None:
        self.api = DaprApi(_StubComponentRegistry())

    def test_unwrap_noop_when_not_dapr_event(self) -> None:
        event = CloudEvent(id="1", type="example.event", source="/example", data={"foo": "bar"})

        result_event, was_unwrapped = self.api._unwrap_nested_cloudevent(event)

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

        result_event, was_unwrapped = self.api._unwrap_nested_cloudevent(event)

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

        result_event, was_unwrapped = self.api._unwrap_nested_cloudevent(event)

        assert was_unwrapped is True
        assert result_event.id == inner_event["id"]
        assert result_event.type == inner_event["type"]
        assert result_event.data == inner_event["data"]
