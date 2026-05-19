"""Unit tests for DaprEventing.publish."""

from unittest.mock import AsyncMock, MagicMock


from blueprint.agents.io.api.eventing.dapr import DaprEventing
from blueprint.agents.models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.models.result import ProcessingResult


def _wire_processing_result(mock_registry: MagicMock, result: ProcessingResult) -> None:
    """Configure mock registry's processing service to return `result`."""
    mock_registry.get_service.return_value.process_event = AsyncMock(return_value=result)
    mock_registry.correlation_context.set.return_value = MagicMock()


class TestDaprEventingPublish:
    async def test_processed_result_returns_success(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        processed_result: ProcessingResult,
    ) -> None:
        _wire_processing_result(mock_registry, processed_result)
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result == {"status": "SUCCESS"}

    async def test_no_handler_result_returns_retry(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        _wire_processing_result(mock_registry, unhandled_result)
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "RETRY"

    async def test_no_handler_retry_includes_reason(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
        unhandled_result: ProcessingResult,
    ) -> None:
        _wire_processing_result(mock_registry, unhandled_result)
        result = await dapr_eventing.publish("topic", cloud_event)
        assert "reason" in result

    async def test_retryable_error_returns_retry(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(
            side_effect=RetryableHandlerError(status="error", reason="transient failure")
        )
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "RETRY"
        assert result["reason"] == "transient failure"

    async def test_invalid_event_error_returns_drop(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(
            side_effect=InvalidEventError(status="invalid", reason="bad schema")
        )
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "DROP"
        assert result["reason"] == "bad schema"

    async def test_critical_error_returns_retry(
        self,
        dapr_eventing: DaprEventing,
        mock_registry: MagicMock,
        cloud_event: CloudEvent,
    ) -> None:
        mock_registry.get_service.return_value.process_event = AsyncMock(side_effect=CriticalHandlerError(status="critical", reason="oom"))
        mock_registry.correlation_context.set.return_value = MagicMock()
        result = await dapr_eventing.publish("topic", cloud_event)
        assert result["status"] == "RETRY"
        assert result["reason"] == "oom"


class TestDaprEventingSubscribe:
    async def test_subscribe_returns_empty_dict(self, dapr_eventing: DaprEventing) -> None:
        result = await dapr_eventing.subscribe("some-topic")
        assert result == {}
