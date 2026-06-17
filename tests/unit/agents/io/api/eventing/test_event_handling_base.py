"""Unit tests for EventHandlingBase._unwrap_nested_cloud_event, handle_event, and retry logic."""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.io.api.eventing.event_handling_base import EventHandlingBase
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.models.result import ProcessingResult


# ---------------------------------------------------------------------------
# Minimal concrete subclass used for retry tests
# ---------------------------------------------------------------------------


class _RetryEventing(EventHandlingBase):
    """Concrete EventHandlingBase with a controllable _connect_and_subscribe."""

    def __init__(self) -> None:
        super().__init__(should_register=False)
        self.connect_mock = AsyncMock()

    async def _connect_and_subscribe(self) -> None:
        await self.connect_mock()

    async def publish(self, topic: str, event: CloudEvent) -> dict[str, Any]:
        return {}

    async def subscribe(self, topic: str, queue_group: str | None = None) -> dict[str, Any]:
        return {}


@pytest.fixture
def eventing(mock_registry: MagicMock, mock_config: MagicMock) -> _RetryEventing:
    """_RetryEventing with infinite retries and zero delay by default."""
    mock_config.get.side_effect = lambda key, default=None: {
        "event_client_max_retries": -1,
        "event_client_retry_delay": 0.0,
    }.get(key, default)
    return _RetryEventing()

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


# ---------------------------------------------------------------------------
# EventHandlingBase retry logic (on_startup / _start_with_retry / on_shutdown)
# ---------------------------------------------------------------------------

_SLEEP_PATH = "blueprint.agents.io.api.eventing.event_handling_base.asyncio.sleep"


class TestStartWithRetry:
    async def test_on_startup_returns_immediately_without_raising(self, eventing: _RetryEventing) -> None:
        eventing.connect_mock.side_effect = Exception("broker down")
        await eventing.on_startup()  # must not raise even though connect will fail

    async def test_on_startup_creates_a_background_task(self, eventing: _RetryEventing) -> None:
        await eventing.on_startup()
        assert isinstance(eventing._retry_task, asyncio.Task)

    async def test_successful_first_attempt_calls_connect_once(self, eventing: _RetryEventing) -> None:
        await eventing.on_startup()
        await eventing._retry_task
        eventing.connect_mock.assert_awaited_once()

    async def test_retries_on_transient_failure_then_succeeds(self, eventing: _RetryEventing) -> None:
        eventing.connect_mock.side_effect = [Exception("transient"), None]
        with patch(_SLEEP_PATH, new_callable=AsyncMock):
            await eventing.on_startup()
            await eventing._retry_task
        assert eventing.connect_mock.await_count == 2

    async def test_max_retries_zero_raises_after_single_attempt(
        self, eventing: _RetryEventing, mock_config: MagicMock
    ) -> None:
        mock_config.get.side_effect = lambda key, default=None: {
            "event_client_max_retries": 0,
            "event_client_retry_delay": 0.0,
        }.get(key, default)
        eventing.connect_mock.side_effect = ConnectionError("broker down")

        await eventing.on_startup()
        with pytest.raises(ConnectionError):
            await eventing._retry_task
        eventing.connect_mock.assert_awaited_once()

    async def test_max_retries_exhausted_calls_connect_n_plus_one_times(
        self, eventing: _RetryEventing, mock_config: MagicMock
    ) -> None:
        mock_config.get.side_effect = lambda key, default=None: {
            "event_client_max_retries": 2,
            "event_client_retry_delay": 0.0,
        }.get(key, default)
        eventing.connect_mock.side_effect = ConnectionError("broker down")

        with patch(_SLEEP_PATH, new_callable=AsyncMock):
            await eventing.on_startup()
            with pytest.raises(ConnectionError):
                await eventing._retry_task
        assert eventing.connect_mock.await_count == 3  # 1 initial + 2 retries

    async def test_succeeds_on_last_allowed_retry(
        self, eventing: _RetryEventing, mock_config: MagicMock
    ) -> None:
        mock_config.get.side_effect = lambda key, default=None: {
            "event_client_max_retries": 2,
            "event_client_retry_delay": 0.0,
        }.get(key, default)
        eventing.connect_mock.side_effect = [Exception("fail"), Exception("fail"), None]

        with patch(_SLEEP_PATH, new_callable=AsyncMock):
            await eventing.on_startup()
            await eventing._retry_task  # must not raise
        assert eventing.connect_mock.await_count == 3

    async def test_on_shutdown_cancels_in_progress_retry_task(self, eventing: _RetryEventing) -> None:
        task_reached_sleep = asyncio.Event()
        never_resolves = asyncio.Event()

        async def hang(*args: Any, **kwargs: Any) -> None:
            task_reached_sleep.set()
            await never_resolves.wait()

        eventing.connect_mock.side_effect = Exception("fail")
        with patch(_SLEEP_PATH, side_effect=hang):
            await eventing.on_startup()
            await task_reached_sleep.wait()  # asyncio.Event.wait() doesn't use asyncio.sleep
            await eventing.on_shutdown()

        assert eventing._retry_task.done()
        assert eventing._retry_task.cancelled()

    async def test_on_shutdown_before_startup_is_noop(self, eventing: _RetryEventing) -> None:
        await eventing.on_shutdown()  # _retry_task is None — must not raise

    async def test_on_shutdown_after_completed_task_is_noop(self, eventing: _RetryEventing) -> None:
        await eventing.on_startup()
        await eventing._retry_task  # let connect succeed
        await eventing.on_shutdown()  # task already done — must not raise
