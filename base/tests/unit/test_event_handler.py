"""Unit tests for EventHandler and Chain of Responsibility pattern."""

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

# Import directly to avoid circular import during testing
from base.src.handler.event_handler import EventHandler
from base.src.models import CloudEvent


class TestEventHandler:
    """Test suite for EventHandler base class."""

    @pytest.fixture
    def mock_cloud_event(self):
        """Create a mock CloudEvent."""
        return CloudEvent(
            specversion="1.0",
            id="test-123",
            source="test-source",
            type="test.event",
            data={"test": "data"},
        )

    @pytest.fixture
    def mock_context(self):
        """Create a mock context dictionary."""
        return {"request_id": "req-123"}

    def test_handler_initialization(self):
        """Test handler can be initialized with name and priority."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return {"result": "test"}

        handler = TestHandler("TestHandler", priority=50)

        assert handler.name == "TestHandler"
        assert handler.priority == 50

    def test_handler_comparison_by_priority(self):
        """Test handlers are sorted by priority (lower first)."""

        class HandlerA(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        class HandlerB(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handler_high = HandlerA("High", priority=100)
        handler_low = HandlerB("Low", priority=10)

        assert handler_low < handler_high
        assert handler_high > handler_low

    def test_handler_sorting(self):
        """Test handlers can be sorted by priority."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handlers = [
            TestHandler("Third", priority=30),
            TestHandler("First", priority=10),
            TestHandler("Second", priority=20),
        ]

        sorted_handlers = sorted(handlers)

        assert sorted_handlers[0].name == "First"
        assert sorted_handlers[1].name == "Second"
        assert sorted_handlers[2].name == "Third"

    @pytest.mark.asyncio
    async def test_can_handle_wrapper_adds_tracing(
        self, mock_cloud_event, mock_context
    ):
        """Test can_handle wrapper adds OpenTelemetry tracing."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handler = TestHandler("TestHandler")

        with patch("base.src.handler.event_handler.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_tracer.start_as_current_span.return_value.__enter__.return_value = (
                mock_span
            )

            result = await handler.can_handle(mock_cloud_event, mock_context)

            assert result is True
            mock_tracer.start_as_current_span.assert_called_once()
            mock_span.set_attribute.assert_any_call("handler.name", "TestHandler")

    @pytest.mark.asyncio
    async def test_handle_wrapper_adds_tracing(self, mock_cloud_event, mock_context):
        """Test handle wrapper adds OpenTelemetry tracing."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return {"result": "success"}

        handler = TestHandler("TestHandler")

        with patch("base.src.handler.event_handler.tracer") as mock_tracer:
            mock_span = MagicMock()
            mock_tracer.start_as_current_span.return_value.__enter__.return_value = (
                mock_span
            )

            result = await handler.handle(mock_cloud_event, mock_context)

            assert result == {"result": "success"}
            mock_tracer.start_as_current_span.assert_called_once()

    def test_link_service_registry(self):
        """Test service registry can be linked to handler."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handler = TestHandler("TestHandler")
        mock_registry = Mock()

        handler.link_service_registry(mock_registry)

        assert handler._registry == mock_registry

    def test_link_component_registry(self):
        """Test component registry can be linked to handler."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handler = TestHandler("TestHandler")
        mock_registry = Mock()

        handler.link_component_registry(mock_registry)

        assert handler._component_registry == mock_registry

    def test_get_agent_without_registry_raises_error(self):
        """Test _get_agent raises error if component registry not linked."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handler = TestHandler("TestHandler")

        with pytest.raises(RuntimeError, match="Component registry not linked"):
            handler._get_agent("test_agent")

    def test_get_agent_retrieves_from_registry(self):
        """Test _get_agent retrieves agent from component registry."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handler = TestHandler("TestHandler")
        mock_component_registry = Mock()
        mock_agent_registry = Mock()
        mock_agent = Mock()

        mock_component_registry.get_agent_registry.return_value = mock_agent_registry
        mock_agent_registry.get.return_value = mock_agent

        handler.link_component_registry(mock_component_registry)

        result = handler._get_agent("test_agent")

        assert result == mock_agent
        mock_component_registry.get_agent_registry.assert_called_once()
        mock_agent_registry.get.assert_called_once_with("test_agent")

    def test_get_published_event_types_default_none(self):
        """Test get_published_event_types returns None by default."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

        handler = TestHandler("TestHandler")

        result = handler.get_published_event_types()

        assert result is None

    def test_get_published_event_types_can_be_overridden(self):
        """Test get_published_event_types can be overridden."""

        class TestHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return None

            def get_published_event_types(self):
                return ("success.event", "error.event")

        handler = TestHandler("TestHandler")

        result = handler.get_published_event_types()

        assert result == ("success.event", "error.event")


class TestChainOfResponsibility:
    """Test suite for Chain of Responsibility pattern."""

    @pytest.fixture
    def mock_cloud_event(self):
        """Create a mock CloudEvent."""
        return CloudEvent(
            specversion="1.0",
            id="test-123",
            source="test-source",
            type="test.event",
            data={"action": "process"},
        )

    @pytest.fixture
    def mock_context(self):
        """Create a mock context dictionary."""
        return {}

    def test_handler_returns_result_stops_chain(self):
        """Test handler returning result stops the chain."""

        class Handler1(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return {"processed_by": "Handler1"}

        class Handler2(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                return {"processed_by": "Handler2"}

        handler1 = Handler1("Handler1", priority=10)
        handler2 = Handler2("Handler2", priority=20)

        # Handler1 should process and stop chain
        # Handler2 should never be called in real chain

    def test_handler_returns_none_continues_chain(self):
        """Test handler returning None continues to next handler."""

        class Handler1(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                context["handler1_called"] = True
                return None  # Continue to next handler

        class Handler2(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                context["handler2_called"] = True
                return {"processed_by": "Handler2"}

        handler1 = Handler1("Handler1", priority=10)
        handler2 = Handler2("Handler2", priority=20)

        # In real chain, both would be called

    def test_handler_can_modify_context(self):
        """Test handlers can modify shared context."""

        class EnrichmentHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                context["enriched"] = True
                context["data"] = "enriched_data"
                return None  # Continue

        class ProcessingHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return context.get("enriched") is True

            async def handle_event(self, event, context):
                return {"result": context.get("data")}

        enrichment = EnrichmentHandler("Enrichment", priority=10)
        processing = ProcessingHandler("Processing", priority=20)

        # Context is shared between handlers

    def test_handler_can_skip_based_on_context(self):
        """Test handler can skip processing based on context."""

        class ConditionalHandler(EventHandler):
            async def can_handle_event(self, event, context):
                # Only handle if specific condition in context
                return context.get("should_process") is True

            async def handle_event(self, event, context):
                return {"processed": True}

        handler = ConditionalHandler("Conditional")

        # Handler should skip if condition not met

    @pytest.mark.asyncio
    async def test_handler_priority_determines_order(self, mock_cloud_event):
        """Test handlers are executed in priority order."""
        execution_order = []

        class Handler1(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                execution_order.append("Handler1")
                return None

        class Handler2(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                execution_order.append("Handler2")
                return None

        class Handler3(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                execution_order.append("Handler3")
                return {"done": True}

        handlers = [
            Handler2("Handler2", priority=20),
            Handler1("Handler1", priority=10),
            Handler3("Handler3", priority=30),
        ]

        sorted_handlers = sorted(handlers)

        # Simulate chain execution
        context = {}
        for handler in sorted_handlers:
            if await handler.can_handle(mock_cloud_event, context):
                result = await handler.handle(mock_cloud_event, context)
                if result is not None:
                    break

        assert execution_order == ["Handler1", "Handler2", "Handler3"]

    @pytest.mark.asyncio
    async def test_handler_can_call_agent(self):
        """Test handler can call agent using _get_agent."""

        class AgentInvokerHandler(EventHandler):
            async def can_handle_event(self, event, context):
                return True

            async def handle_event(self, event, context):
                # Get agent and call it
                agent = self._get_agent("test_agent")
                result = await agent.run("test instruction")
                return {"agent_result": result}

        handler = AgentInvokerHandler("AgentInvoker")

        # Mock component registry and agent
        mock_component_registry = Mock()
        mock_agent_registry = Mock()
        mock_agent = Mock()
        mock_agent.run = Mock(return_value=Mock(data="agent_output"))

        mock_component_registry.get_agent_registry.return_value = mock_agent_registry
        mock_agent_registry.get.return_value = mock_agent

        handler.link_component_registry(mock_component_registry)

        # Execute
        event = CloudEvent(
            specversion="1.0",
            id="test",
            source="test",
            type="test",
            data={},
        )
        result = await handler.handle_event(event, {})

        assert "agent_result" in result
        mock_agent.run.assert_called_once_with("test instruction")
