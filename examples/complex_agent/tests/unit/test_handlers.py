"""Unit tests for the custom handler implementations."""

import pytest

from blueprint.agents.models.events import CloudEvent

from examples.complex_agent.src.handlers import AgentInvokerHandler, SimpleProcessorHandler
from examples.complex_agent.src.models import CustomPayload


@pytest.fixture
def mock_event():
    """Provides a mock CloudEvent for handler tests."""
    return CloudEvent(
        specversion="1.0",
        id="event-123",
        source="/test-suite",
        type="com.example.test",
        data={"key": "value"},
    )


@pytest.fixture
def mock_context():
    """Provides a mock context dictionary for handler tests."""
    return {}


class TestAgentInvokerHandler:
    """Tests for AgentInvokerHandler."""

    @pytest.mark.asyncio
    async def test_can_handle_with_invoke_agent_action(self):
        """Ensures handler recognizes invoke_agent action."""
        handler = AgentInvokerHandler()

        payload = CustomPayload(invoice_text="Test invoice", details={"action": "invoke_agent"})

        event = CloudEvent(
            specversion="1.0",
            id="test-123",
            source="/test",
            type="test.event",
            data=payload,
        )

        assert await handler.can_handle(event, {}) is True

    @pytest.mark.asyncio
    async def test_cannot_handle_without_invoke_agent_action(self):
        """Ensures handler rejects events without invoke_agent action."""
        handler = AgentInvokerHandler()

        payload = CustomPayload(invoice_text="Test invoice", details={"action": "other_action"})

        event = CloudEvent(
            specversion="1.0",
            id="test-123",
            source="/test",
            type="test.event",
            data=payload,
        )

        assert await handler.can_handle(event, {}) is False

    @pytest.mark.asyncio
    async def test_handle_returns_error_result_when_agent_missing(self):
        """handle should surface error result when registry is not linked."""
        handler = AgentInvokerHandler()

        payload = CustomPayload(invoice_text="Test invoice text", details={"action": "invoke_agent"})

        event = CloudEvent(
            specversion="1.0",
            id="test-123",
            source="/test",
            type="test.event",
            data=payload,
        )

        result = await handler.handle(event, {})

        assert result.event_type == "invoice.analysis.error"
        assert result.metadata["error_type"] == "RuntimeError"


class TestSimpleProcessorHandler:
    """Tests for SimpleProcessorHandler behavior."""

    @pytest.mark.asyncio
    async def test_can_handle_after_validation(self):
        """Ensures SimpleProcessorHandler handles matching payloads."""
        handler = SimpleProcessorHandler()

        payload = CustomPayload(
            invoice_text="Test invoice",
            details={"action": "simple_process", "invoice_id": "inv-1", "line_items": []},
        )

        event = CloudEvent(
            specversion="1.0",
            id="test-789",
            source="/test",
            type="test.event",
            data=payload,
        )

        assert await handler.can_handle(event, {}) is True

    @pytest.mark.asyncio
    async def test_simple_processor_rejects_non_custom_payload(self, mock_context):
        handler = SimpleProcessorHandler()
        event = CloudEvent(
            specversion="1.0",
            id="test-000",
            source="/test",
            type="test.event",
            data={"details": {"action": "simple_process"}},
        )

        assert await handler.can_handle(event, mock_context) is False
