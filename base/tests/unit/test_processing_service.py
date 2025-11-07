"""Unit tests for ProcessingService and handler chain orchestration."""

from unittest.mock import Mock
from uuid import uuid4

import pytest

# Import directly to avoid circular import during testing
from base.src.handler.event_handler import EventHandler
from base.src.models import CloudEvent
from base.src.services.processing_service import ProcessingService


class TestProcessingService:
    """Test suite for ProcessingService."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        config = Mock()
        config.get.return_value = "test-app"
        return config

    @pytest.fixture
    def mock_component_registry(self):
        """Create mock component registry."""
        registry = Mock()
        registry.get_handlers.return_value = []
        registry.get_all_runtimes.return_value = {}
        return registry

    @pytest.fixture
    def processing_service(self, mock_config, mock_component_registry):
        """Create ProcessingService instance."""
        return ProcessingService(mock_config, mock_component_registry)

    @pytest.fixture
    def mock_cloud_event(self):
        """Create a mock CloudEvent."""
        return CloudEvent(
            specversion="1.0",
            id=str(uuid4()),
            source="test-source",
            type="test.event",
            data={"test": "data"},
        )

    @pytest.mark.asyncio
    async def test_process_event_with_no_handlers(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test processing event when no handlers are registered."""
        mock_component_registry.get_handlers.return_value = []

        result = await processing_service.process_event(mock_cloud_event)

        assert result.type == "agent.output.test.event"
        assert result.data["status"] == "no_handler_found"
        assert result.data["result"] is None

    @pytest.mark.asyncio
    async def test_process_event_with_handler_that_processes(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test processing event with handler that returns result."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return {"processed": True, "handler": "TestHandler"}

        handler = TestHandler("TestHandler", priority=10)
        mock_component_registry.get_handlers.return_value = [handler]

        result = await processing_service.process_event(mock_cloud_event)

        assert result.type == "agent.output.test.event"
        assert result.data["status"] == "processed"
        assert result.data["result"]["processed"] is True

    @pytest.mark.asyncio
    async def test_process_event_chain_stops_at_first_result(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test handler chain stops at first handler that returns result."""
        handler2_called = False

        class Handler1(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return {"processed_by": "Handler1"}

        class Handler2(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                nonlocal handler2_called
                handler2_called = True
                return {"processed_by": "Handler2"}

        handler1 = Handler1("Handler1", priority=10)
        handler2 = Handler2("Handler2", priority=20)

        mock_component_registry.get_handlers.return_value = [handler1, handler2]

        result = await processing_service.process_event(mock_cloud_event)

        assert result.data["result"]["processed_by"] == "Handler1"
        assert not handler2_called  # Handler2 should not be called

    @pytest.mark.asyncio
    async def test_process_event_chain_continues_on_none(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test handler chain continues when handler returns None."""
        handler1_called = False
        handler2_called = False

        class Handler1(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                nonlocal handler1_called
                handler1_called = True
                context["handler1_processed"] = True
                return None  # Continue to next handler

        class Handler2(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                nonlocal handler2_called
                handler2_called = True
                return {"processed_by": "Handler2"}

        handler1 = Handler1("Handler1", priority=10)
        handler2 = Handler2("Handler2", priority=20)

        mock_component_registry.get_handlers.return_value = [handler1, handler2]

        result = await processing_service.process_event(mock_cloud_event)

        assert handler1_called
        assert handler2_called
        assert result.data["result"]["processed_by"] == "Handler2"

    @pytest.mark.asyncio
    async def test_process_event_respects_handler_priority(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test handlers are executed in priority order."""
        execution_order = []

        class HighPriorityHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                execution_order.append("high")
                return None

        class LowPriorityHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                execution_order.append("low")
                return {"done": True}

        high = HighPriorityHandler("High", priority=100)
        low = LowPriorityHandler("Low", priority=10)

        # Register in wrong order
        mock_component_registry.get_handlers.return_value = [high, low]

        await processing_service.process_event(mock_cloud_event)

        # Low priority (10) should execute before high priority (100)
        assert execution_order == ["low"]

    @pytest.mark.asyncio
    async def test_process_event_handler_can_skip(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test handler can skip processing based on can_handle_event."""
        handler1_called = False
        handler2_called = False

        class SkippingHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return False  # Skip this handler

            async def handle_event(self, event, context):
                nonlocal handler1_called
                handler1_called = True
                return {"skipped": True}

        class ProcessingHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                nonlocal handler2_called
                handler2_called = True
                return {"processed": True}

        handler1 = SkippingHandler("Skipping", priority=10)
        handler2 = ProcessingHandler("Processing", priority=20)

        mock_component_registry.get_handlers.return_value = [handler1, handler2]

        result = await processing_service.process_event(mock_cloud_event)

        assert not handler1_called  # Skipped
        assert handler2_called  # Processed
        assert result.data["result"]["processed"] is True

    @pytest.mark.asyncio
    async def test_process_event_context_shared_between_handlers(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test context is shared and accumulated across handlers."""

        class EnrichmentHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                context["enriched_data"] = "test_data"
                context["validation_passed"] = True
                return None  # Continue

        class ProcessingHandler(EventHandler):
            async def can_handle_event(self, event, context):
                # Only process if enriched
                return context.get("validation_passed") is True

            async def handle_event(self, event, context):
                return {
                    "processed": True,
                    "data": context.get("enriched_data"),
                }

        handler1 = EnrichmentHandler("Enrichment", priority=10)
        handler2 = ProcessingHandler("Processing", priority=20)

        mock_component_registry.get_handlers.return_value = [handler1, handler2]

        result = await processing_service.process_event(mock_cloud_event)

        assert result.data["result"]["processed"] is True
        assert result.data["result"]["data"] == "test_data"

    @pytest.mark.asyncio
    async def test_process_event_handler_exception_propagates(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test exception in handler propagates correctly."""

        class FailingHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                raise ValueError("Handler failed")

        handler = FailingHandler("Failing", priority=10)
        mock_component_registry.get_handlers.return_value = [handler]

        with pytest.raises(ValueError, match="Handler failed"):
            await processing_service.process_event(mock_cloud_event)

    @pytest.mark.asyncio
    async def test_process_event_adds_request_id(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test process_event adds request_id to result."""
        mock_component_registry.get_handlers.return_value = []

        result = await processing_service.process_event(mock_cloud_event)

        assert "request_id" in result.data
        assert result.data["request_id"] is not None

    @pytest.mark.asyncio
    async def test_process_event_with_runtime_name_parameter(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test process_event accepts runtime_name parameter (for compatibility)."""
        mock_component_registry.get_handlers.return_value = []

        # Should not raise error even with runtime_name
        result = await processing_service.process_event(
            mock_cloud_event, runtime_name="test_runtime"
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_health_check_returns_healthy(
        self, processing_service, mock_component_registry
    ):
        """Test health check returns healthy status."""
        mock_component_registry.get_handlers.return_value = []

        result = await processing_service.health_check()

        assert result["status"] == "healthy"
        assert "handlers_count" in result

    @pytest.mark.asyncio
    async def test_health_check_includes_handler_count(
        self, processing_service, mock_component_registry
    ):
        """Test health check includes number of registered handlers."""

        class DummyHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handlers = [
            DummyHandler("Handler1", priority=10),
            DummyHandler("Handler2", priority=20),
        ]
        mock_component_registry.get_handlers.return_value = handlers

        result = await processing_service.health_check()

        assert result["handlers_count"] == 2

    @pytest.mark.asyncio
    async def test_process_event_creates_output_event(
        self, processing_service, mock_cloud_event, mock_component_registry
    ):
        """Test process_event creates proper output CloudEvent."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return {"test": "result"}

        handler = TestHandler("Test", priority=10)
        mock_component_registry.get_handlers.return_value = [handler]

        result = await processing_service.process_event(mock_cloud_event)

        assert result.specversion == "1.0"
        assert result.source == "test-app"
        assert result.type == "agent.output.test.event"
        assert result.subject == mock_cloud_event.subject
        assert result.id is not None
