"""Unit tests for EventHandlingBase._unwrap_nested_cloud_event and handle_event."""

import json
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blueprint.agents.handler.handler_chain import DUPLICATE_CONTEXT_KEY
from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.io.api.eventing.event_handling_base import DUPLICATE_EVENTS_COUNTER, UNHANDLED_EVENTS_COUNTER
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.models.result import ProcessingResult


@contextmanager
def _counters() -> Iterator[dict[str, MagicMock]]:
    """Stand-in counters, one per name, created through the agent's meter as the code does."""
    counters: dict[str, MagicMock] = defaultdict(MagicMock)
    meter = MagicMock()
    meter.create_counter.side_effect = lambda name, **_: counters[name]
    with patch("blueprint.agents.io.api.eventing.event_handling_base.agent_meter", return_value=meter):
        yield counters


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

    async def test_non_processed_status_also_returns_success(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        """A handler chain that returned acknowledges whatever its status (spec sec. 7.2)."""
        mock_registry.get_service.return_value.process_event = AsyncMock(return_value=unhandled_result)
        mock_registry.correlation_context.set.return_value = MagicMock()

        result = await dapr_eventing.handle_event("topic", cloud_event)
        assert result == {"status": "SUCCESS"}

    async def test_non_processed_status_is_not_reported_as_a_fault(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(return_value=unhandled_result)
        mock_registry.correlation_context.set.return_value = MagicMock()

        with caplog.at_level("DEBUG"):
            await dapr_eventing.handle_event("topic", cloud_event)
        assert [r for r in caplog.records if r.levelname in {"WARNING", "ERROR", "CRITICAL"}] == []

    async def test_exceptions_are_not_caught_here(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        """The transport edge classifies failures; catching one here would acknowledge it."""
        mock_registry.get_service.return_value.process_event = AsyncMock(side_effect=RuntimeError("boom"))
        mock_registry.correlation_context.set.return_value = MagicMock()

        with pytest.raises(RuntimeError, match="boom"):
            await dapr_eventing.handle_event("topic", cloud_event)


class TestProcessCloudEventDoesNotLogAndReraise:
    """P2 -- the transport edge is the single place that logs a failure and settles it."""

    async def test_exception_propagates(self, dapr_eventing: DaprEventing, cloud_event: CloudEvent) -> None:
        dapr_eventing._dispatch_cloud_event = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="boom"):
            await dapr_eventing._process_cloud_event(cloud_event, {}, "orders.created")

    async def test_exception_is_not_logged_here(
        self, dapr_eventing: DaprEventing, cloud_event: CloudEvent, caplog: pytest.LogCaptureFixture
    ) -> None:
        dapr_eventing._dispatch_cloud_event = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        with caplog.at_level("ERROR"), pytest.raises(RuntimeError):
            await dapr_eventing._process_cloud_event(cloud_event, {}, "orders.created")
        assert caplog.records == []


class TestUnhandledEventAccounting:
    """P2 -- an unmatched event is ordinary: counted for ratio, never reported as a fault."""

    @staticmethod
    def _returning(dapr_eventing: DaprEventing, result: ProcessingResult) -> None:
        dapr_eventing._dispatch_cloud_event = AsyncMock(return_value=result)  # type: ignore[method-assign]

    async def test_unmatched_event_is_counted(
        self, dapr_eventing: DaprEventing, cloud_event: CloudEvent, unhandled_result: ProcessingResult
    ) -> None:
        self._returning(dapr_eventing, unhandled_result)

        with _counters() as counters:
            await dapr_eventing._process_cloud_event(cloud_event, {}, "orders.created")

        counters[UNHANDLED_EVENTS_COUNTER].add.assert_called_once_with(1, {"agent": "<root>", "topic": "orders.created"})

    async def test_matched_event_is_not_counted(
        self, dapr_eventing: DaprEventing, cloud_event: CloudEvent, processed_result: ProcessingResult
    ) -> None:
        self._returning(dapr_eventing, processed_result)

        with _counters() as counters:
            await dapr_eventing._process_cloud_event(cloud_event, {}, "orders.created")

        counters[UNHANDLED_EVENTS_COUNTER].add.assert_not_called()

    async def test_every_unmatched_event_is_counted(
        self, dapr_eventing: DaprEventing, cloud_event: CloudEvent, unhandled_result: ProcessingResult
    ) -> None:
        """The count is read as a ratio against received volume, so it must not be deduplicated."""
        self._returning(dapr_eventing, unhandled_result)

        with _counters() as counters:
            for _ in range(5):
                await dapr_eventing._process_cloud_event(cloud_event, {}, "orders.created")

        assert counters[UNHANDLED_EVENTS_COUNTER].add.call_count == 5

    async def test_unmatched_event_is_not_reported_as_a_fault(
        self,
        dapr_eventing: DaprEventing,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Finding no work in an event is the handler doing its job, not an error."""
        self._returning(dapr_eventing, unhandled_result)

        with caplog.at_level("DEBUG"):
            await dapr_eventing._process_cloud_event(cloud_event, {}, "orders.created")

        assert [r for r in caplog.records if r.levelname in {"WARNING", "ERROR", "CRITICAL"}] == []

    async def test_it_is_counted_on_the_agents_own_meter(
        self, dapr_eventing: DaprEventing, cloud_event: CloudEvent, unhandled_result: ProcessingResult
    ) -> None:
        """Created at import on the global meter, it reported under the root's resource (C2)."""
        self._returning(dapr_eventing, unhandled_result)
        meter = MagicMock()
        with patch("blueprint.agents.io.api.eventing.event_handling_base.agent_meter", return_value=meter) as agent_meter:
            await dapr_eventing._process_cloud_event(cloud_event, {}, "orders.created", namespace="orders")

        assert agent_meter.call_args.args[0] == "orders"
        meter.create_counter.return_value.add.assert_called_once_with(1, {"agent": "orders", "topic": "orders.created"})

    async def test_many_distinct_topics_leave_no_state_behind(
        self, dapr_eventing: DaprEventing, cloud_event: CloudEvent, unhandled_result: ProcessingResult
    ) -> None:
        """Under Dapr the topic comes from a URL path, so remembering each one is caller-controlled growth."""
        self._returning(dapr_eventing, unhandled_result)
        # The first event creates this agent's counter; that is per (counter, agent), not per topic.
        await dapr_eventing._process_cloud_event(cloud_event, {}, "topic.first")
        before = len(dapr_eventing.__dict__)

        for index in range(100):
            await dapr_eventing._process_cloud_event(cloud_event, {}, f"topic.{index}")

        assert len(dapr_eventing.__dict__) == before
        assert len(dapr_eventing.__dict__["_event_counters"]) == 1


# ---------------------------------------------------------------------------
# Duplicate accounting (P4, spec sec. 7.4)
# ---------------------------------------------------------------------------


class TestDuplicateAccounting:
    """A deduplicated event reaches the edge looking unmatched; it must not be counted as one."""

    @staticmethod
    def _flagging_process_event(result: ProcessingResult) -> AsyncMock:
        """Stand in for the handler chain marking the context as a duplicate."""

        async def _process_event(event, context, *args, **kwargs):
            context[DUPLICATE_CONTEXT_KEY] = True
            return result

        return AsyncMock(side_effect=_process_event)

    async def test_duplicate_is_counted_as_a_duplicate_not_as_unhandled(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        mock_registry.get_service.return_value.process_event = self._flagging_process_event(unhandled_result)
        mock_registry.correlation_context.set.return_value = MagicMock()

        with _counters() as counters:
            await dapr_eventing.handle_event("orders", cloud_event)

        counters[DUPLICATE_EVENTS_COUNTER].add.assert_called_once_with(1, {"agent": "<root>", "topic": "orders"})
        counters[UNHANDLED_EVENTS_COUNTER].add.assert_not_called()

    async def test_duplicate_still_acknowledges(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        """Redelivering a duplicate forever would be the one thing worse than processing it twice."""
        mock_registry.get_service.return_value.process_event = self._flagging_process_event(unhandled_result)
        mock_registry.correlation_context.set.return_value = MagicMock()

        result = await dapr_eventing.handle_event("orders", cloud_event)

        assert result == {"status": "SUCCESS"}

    async def test_unmatched_event_is_still_counted_as_unhandled(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(return_value=unhandled_result)
        mock_registry.correlation_context.set.return_value = MagicMock()

        with _counters() as counters:
            await dapr_eventing.handle_event("orders", cloud_event)

        counters[UNHANDLED_EVENTS_COUNTER].add.assert_called_once_with(1, {"agent": "<root>", "topic": "orders"})
        counters[DUPLICATE_EVENTS_COUNTER].add.assert_not_called()
