"""Unit tests for ProcessingService with concrete handlers."""

from typing import Any
from uuid import uuid4

import pytest

from blueprint.agents.base import EventHandler
from blueprint.agents.config import Config
from blueprint.agents.models import (
    CloudEvent,
    HandlerResult,
    ProcessingResult,
    ProcessingStatus,
)
from blueprint.agents.models.errors import CriticalHandlerError, InvalidEventError, RetryableHandlerError
from blueprint.agents.registry.component_registry import ComponentRegistry
from blueprint.agents.services.processing_service import ProcessingService


class ConcreteHandler(EventHandler):
    """Concrete handler for testing."""

    def __init__(self, name: str = "TestHandler", priority: int = 100, should_handle: bool = True, result: Any | None = None):
        super().__init__(name, priority)
        self.should_handle = should_handle
        self.result = result
        self.handle_called = False
        self.can_handle_called = False
        self.on_startup_called = False
        self.on_shutdown_called = False

    async def on_startup(self):
        """Startup hook."""
        self.on_startup_called = True

    async def on_shutdown(self):
        """Shutdown hook."""
        self.on_shutdown_called = True

    async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
        """Determine if handler should process the event."""
        self.can_handle_called = True
        return self.should_handle

    async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
        """Process the event."""
        self.handle_called = True
        return self.result


class TestProcessingService:
    """Test suite for ProcessingService."""

    @pytest.fixture
    def config(self):
        """Create real Config instance."""
        return Config()

    @pytest.fixture
    def component_registry(self, config):
        """Create real ComponentRegistry instance."""
        return ComponentRegistry(config)

    @pytest.fixture
    def processing_service(self, config, component_registry):
        """Create ProcessingService instance."""
        return ProcessingService(config, component_registry)

    @pytest.fixture
    def cloud_event(self):
        """Create a CloudEvent."""
        return CloudEvent(
            specversion="1.0",
            id=str(uuid4()),
            source="test-source",
            type="test.event",
            data={"test": "data"},
        )

    @pytest.mark.asyncio
    async def test_process_event_with_no_handlers(self, processing_service, cloud_event):
        """Test processing event when no handlers are registered."""
        result = await processing_service.process_event(cloud_event)

        assert isinstance(result, ProcessingResult)
        assert result.status == ProcessingStatus.NO_HANDLER_FOUND
        assert result.result == []
        assert result.message == "No handler processed this event"

    @pytest.mark.asyncio
    async def test_process_event_with_handler_that_processes(self, processing_service, component_registry, cloud_event):
        """Test processing event with handler that returns result."""
        handler = ConcreteHandler("TestHandler", priority=10, should_handle=True, result={"processed": True})
        component_registry.register_handler(handler)

        result = await processing_service.process_event(cloud_event)

        assert result.status == ProcessingStatus.PROCESSED
        assert len(result.result) == 1
        assert result.result[0].data == {"processed": True}
        assert result.message == "Message acknowledged"
        assert handler.can_handle_called
        assert handler.handle_called

    @pytest.mark.asyncio
    async def test_process_event_chain_stops_at_first_result(self, processing_service, component_registry, cloud_event):
        """Test handler chain stops at first handler that returns result."""
        handler1 = ConcreteHandler("Handler1", priority=10, should_handle=True, result={"processed_by": "Handler1"})
        handler2 = ConcreteHandler("Handler2", priority=20, should_handle=True, result={"processed_by": "Handler2"})

        component_registry.register_handler(handler1)
        component_registry.register_handler(handler2)

        result = await processing_service.process_event(cloud_event)

        assert result.status == ProcessingStatus.PROCESSED
        assert result.result[0].data == {"processed_by": "Handler1"}
        assert handler1.handle_called
        assert not handler2.handle_called  # Handler2 should not be called

    @pytest.mark.asyncio
    async def test_process_event_chain_continues_on_none(self, processing_service, component_registry, cloud_event):
        """Test handler chain continues when handler returns None."""
        handler1 = ConcreteHandler("Handler1", priority=10, should_handle=True, result=None)
        handler2 = ConcreteHandler("Handler2", priority=20, should_handle=True, result={"processed_by": "Handler2"})

        component_registry.register_handler(handler1)
        component_registry.register_handler(handler2)

        result = await processing_service.process_event(cloud_event)

        assert handler1.handle_called
        assert handler2.handle_called
        assert result.status == ProcessingStatus.PROCESSED
        assert result.result[0].data == {"processed_by": "Handler2"}

    @pytest.mark.asyncio
    async def test_process_event_respects_handler_priority(self, processing_service, component_registry, cloud_event):
        """Test handlers are executed in priority order."""
        execution_order = []

        class TrackingHandler(ConcreteHandler):
            def __init__(self, name: str, priority: int, order_list: list):
                super().__init__(name, priority, should_handle=True, result=None)
                self.order_list = order_list

            async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
                self.order_list.append(self.get_name())
                return await super().handle_event(event, context)

        high = TrackingHandler("High", priority=100, order_list=execution_order)
        low = TrackingHandler("Low", priority=10, order_list=execution_order)

        component_registry.register_handler(high)
        component_registry.register_handler(low)

        result = await processing_service.process_event(cloud_event)

        # Low priority (10) should execute before high priority (100)
        assert execution_order == ["Low", "High"]
        assert result.status == ProcessingStatus.NO_HANDLER_FOUND

    @pytest.mark.asyncio
    async def test_process_event_handler_can_skip(self, processing_service, component_registry, cloud_event):
        """Test handler can skip processing based on can_handle_event."""
        handler1 = ConcreteHandler("Skipping", priority=10, should_handle=False, result={"skipped": True})
        handler2 = ConcreteHandler("Processing", priority=20, should_handle=True, result={"processed": True})

        component_registry.register_handler(handler1)
        component_registry.register_handler(handler2)

        result = await processing_service.process_event(cloud_event)

        assert not handler1.handle_called  # Skipped
        assert handler2.handle_called  # Processed
        assert result.status == ProcessingStatus.PROCESSED
        assert result.result[0].data == {"processed": True}

    @pytest.mark.asyncio
    async def test_process_event_context_shared_between_handlers(self, processing_service, component_registry, cloud_event):
        """Test context is shared and accumulated across handlers."""

        class ContextAwareHandler(ConcreteHandler):
            async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
                self.handle_called = True
                context["enriched_data"] = "test_data"
                context["validation_passed"] = True
                return None

        class ContextConsumerHandler(ConcreteHandler):
            async def can_handle_event(self, event: CloudEvent, context: dict[str, Any]) -> bool:
                self.can_handle_called = True
                return context.get("validation_passed") is True

            async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
                self.handle_called = True
                return {"processed": True, "data": context.get("enriched_data")}

        handler1 = ContextAwareHandler("Enrichment", priority=10)
        handler2 = ContextConsumerHandler("Processing", priority=20)

        component_registry.register_handler(handler1)
        component_registry.register_handler(handler2)

        result = await processing_service.process_event(cloud_event)

        assert result.status == ProcessingStatus.PROCESSED
        assert result.result[0].data == {"processed": True, "data": "test_data"}

    @pytest.mark.asyncio
    async def test_process_event_handler_exception_propagates(self, processing_service, component_registry, cloud_event):
        """Test exception in handler propagates correctly."""

        class FailingHandler(ConcreteHandler):
            async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
                self.handle_called = True
                raise ValueError("Handler failed")

        handler = FailingHandler("Failing", priority=10)
        component_registry.register_handler(handler)

        with pytest.raises(ValueError, match="Handler failed"):
            await processing_service.process_event(cloud_event)

    @pytest.mark.asyncio
    async def test_process_event_retryable_handler_error(self, processing_service, component_registry, cloud_event):
        """Retryable handler errors propagate for upstream handling."""

        class RetryableFailingHandler(ConcreteHandler):
            async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
                raise RetryableHandlerError(status="retry", reason="transient")

        component_registry.register_handler(RetryableFailingHandler("Retry", priority=10))

        with pytest.raises(RetryableHandlerError):
            await processing_service.process_event(cloud_event)

    @pytest.mark.asyncio
    async def test_process_event_invalid_handler_error(self, processing_service, component_registry, cloud_event):
        """Invalid handler errors propagate for upstream handling."""

        class InvalidFailingHandler(ConcreteHandler):
            async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
                raise InvalidEventError(status="bad", reason="invalid")

        component_registry.register_handler(InvalidFailingHandler("Invalid", priority=10))

        with pytest.raises(InvalidEventError):
            await processing_service.process_event(cloud_event)

    @pytest.mark.asyncio
    async def test_process_event_critical_handler_error(self, processing_service, component_registry, cloud_event):
        """Critical handler errors propagate for upstream handling."""

        class CriticalFailingHandler(ConcreteHandler):
            async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
                raise CriticalHandlerError(status="critical", reason="fatal")

        component_registry.register_handler(CriticalFailingHandler("Critical", priority=10))

        with pytest.raises(CriticalHandlerError):
            await processing_service.process_event(cloud_event)

    @pytest.mark.asyncio
    async def test_process_event_adds_request_id(self, processing_service, cloud_event):
        """Test process_event adds request_id to result."""
        result = await processing_service.process_event(cloud_event)

        assert result.request_id is not None
        assert isinstance(result.request_id, str)

    @pytest.mark.asyncio
    async def test_process_event_with_context(self, processing_service, component_registry, cloud_event):
        """Test process_event passes context to handlers."""

        class ContextCheckHandler(ConcreteHandler):
            async def handle_event(self, event: CloudEvent, context: dict[str, Any]) -> Any | None:
                self.handle_called = True
                return {"has_custom_key": "custom_key" in context}

        handler = ContextCheckHandler("ContextCheck", priority=10)
        component_registry.register_handler(handler)

        result = await processing_service.process_event(cloud_event, context={"custom_key": "custom_value"})

        assert result.status == ProcessingStatus.PROCESSED
        assert result.result[0].data == {"has_custom_key": True}

    @pytest.mark.asyncio
    async def test_process_rest_request(self, processing_service, component_registry):
        """Test process_rest_request converts payload to CloudEvent."""
        handler = ConcreteHandler("TestHandler", priority=10, should_handle=True, result={"processed": True})
        component_registry.register_handler(handler)

        payload = {"user_id": 123, "action": "test"}
        result = await processing_service.process_rest_request(payload)

        assert result.status == ProcessingStatus.PROCESSED
        assert result.result[0].data == {"processed": True}

    @pytest.mark.asyncio
    async def test_process_event_creates_output_event(self, processing_service, component_registry, cloud_event):
        """Test process_event creates proper output CloudEvent."""
        handler = ConcreteHandler("Test", priority=10, should_handle=True, result={"test": "result"})
        component_registry.register_handler(handler)

        result = await processing_service.process_event(cloud_event)

        assert isinstance(result, ProcessingResult)
        assert result.request_id is not None
        assert result.status == ProcessingStatus.PROCESSED

    @pytest.mark.asyncio
    async def test_process_event_with_handler_returning_list_of_results(self, processing_service, component_registry, cloud_event):
        """Test processing event with handler that returns list of HandlerResults."""
        handler_results = [
            HandlerResult(event_type="event.type.one", data={"result": "first"}, metadata={"source": "handler"}),
            HandlerResult(event_type="event.type.two", data={"result": "second"}, metadata={"source": "handler"}),
        ]

        handler = ConcreteHandler("MultiHandler", priority=10, should_handle=True, result=handler_results)
        component_registry.register_handler(handler)

        result = await processing_service.process_event(cloud_event)

        assert result.status == ProcessingStatus.PROCESSED
        assert len(result.result) == 2
        assert result.result[0].data == {"result": "first"}
        assert result.result[1].data == {"result": "second"}

    @pytest.mark.asyncio
    async def test_process_event_with_multiple_results_publishes_each_event(self, processing_service, component_registry, cloud_event):
        """Test that each result with event_type in list is published."""
        handler_results = [
            HandlerResult(event_type="event.published.one", data={"id": 1}, metadata={"index": 0}),
            HandlerResult(event_type="event.published.two", data={"id": 2}, metadata={"index": 1}),
            HandlerResult(event_type=None, data={"id": 3}, metadata={"index": 2}),  # This one should not be published
        ]

        handler = ConcreteHandler("MultiHandler", priority=10, should_handle=True, result=handler_results)
        component_registry.register_handler(handler)

        # Mock the event publisher to track calls
        from unittest.mock import AsyncMock, patch

        with patch.object(processing_service._event_publisher, "publish_handler_event", new_callable=AsyncMock) as mock_publish:
            result = await processing_service.process_event(cloud_event)

            # Should publish exactly 2 events (the ones with event_type)
            assert mock_publish.call_count == 2

            # Verify the calls
            calls = mock_publish.call_args_list
            assert calls[0][1]["event_type"] == "event.published.one"
            assert calls[0][1]["data"] == {"id": 1}
            assert calls[1][1]["event_type"] == "event.published.two"
            assert calls[1][1]["data"] == {"id": 2}
            assert result.status == ProcessingStatus.PROCESSED
            assert len(result.result) == 3

    @pytest.mark.asyncio
    async def test_process_event_with_empty_list_result(self, processing_service, component_registry, cloud_event):
        """Test processing event with handler that returns empty list."""
        handler = ConcreteHandler("EmptyHandler", priority=10, should_handle=True, result=[])
        component_registry.register_handler(handler)

        result = await processing_service.process_event(cloud_event)

        assert result.status == ProcessingStatus.PROCESSED
        assert result.result == []

    @pytest.mark.asyncio
    async def test_process_event_with_mixed_handler_results(self, processing_service, component_registry, cloud_event):
        """Test handler returning list with some results having event_type and some not."""
        handler_results = [
            HandlerResult(event_type="event.success", data={"status": "success"}, metadata={"type": "success"}),
            HandlerResult(event_type=None, data={"internal": "data"}, metadata={"type": "internal"}),
            HandlerResult(event_type="event.notification", data={"message": "notification"}, metadata={"type": "notification"}),
        ]

        handler = ConcreteHandler("MixedHandler", priority=10, should_handle=True, result=handler_results)
        component_registry.register_handler(handler)

        from unittest.mock import AsyncMock, patch

        with patch.object(processing_service._event_publisher, "publish_handler_event", new_callable=AsyncMock) as mock_publish:
            result = await processing_service.process_event(cloud_event)

            # Should publish exactly 2 events (skip the one with event_type=None)
            assert mock_publish.call_count == 2

            # Verify the published events
            calls = mock_publish.call_args_list
            assert calls[0][1]["event_type"] == "event.success"
            assert calls[1][1]["event_type"] == "event.notification"
            assert result.status == ProcessingStatus.PROCESSED
            assert len(result.result) == 3

    @pytest.mark.asyncio
    async def test_process_event_single_result_still_works(self, processing_service, component_registry, cloud_event):
        """Test that single HandlerResult still works (backward compatibility)."""
        single_result = HandlerResult(event_type="event.single", data={"single": "result"}, metadata={"type": "single"})

        handler = ConcreteHandler("SingleHandler", priority=10, should_handle=True, result=single_result)
        component_registry.register_handler(handler)

        from unittest.mock import AsyncMock, patch

        with patch.object(processing_service._event_publisher, "publish_handler_event", new_callable=AsyncMock) as mock_publish:
            result = await processing_service.process_event(cloud_event)

            # Should publish exactly 1 event
            assert mock_publish.call_count == 1
            assert mock_publish.call_args[1]["event_type"] == "event.single"
            assert mock_publish.call_args[1]["data"] == {"single": "result"}
            assert result.status == ProcessingStatus.PROCESSED
            assert result.result[0].data == {"single": "result"}
