"""Unit tests for event handlers in `custom.src.agent.handlers`.

TODO: These tests need to be updated to use HarmonizingInputPayload structure:
- Replace CustomPayload with HarmonizingInputPayload
- Update payload structure to match new schema (subject, data.type, data.properties)
- Update test assertions accordingly
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from base.src.models.events import CloudEvent
from custom.src.agent.handlers import (AgentInvokerHandler, ProcessingHandler,
                                       SimpleProcessorHandler)
from custom.src.models import HarmonizingInputPayload


@pytest.fixture
def mock_event():
    """Provides a mock CloudEvent for handler tests."""
    event = MagicMock(spec=CloudEvent)
    event.data = {"key": "value"}
    event.type = "com.example.test"
    return event


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

        payload = CustomPayload(
            invoice_text="Test invoice", details={"action": "invoke_agent"}
        )

        event = CloudEvent(
            specversion="1.0",
            id="test-123",
            source="/test",
            type="test.event",
            data=payload,
        )

        context = {}
        assert await handler._can_handle(event, context) is True

    @pytest.mark.asyncio
    async def test_cannot_handle_without_invoke_agent_action(self):
        """Ensures handler rejects events without invoke_agent action."""
        handler = AgentInvokerHandler()

        payload = CustomPayload(
            invoice_text="Test invoice", details={"action": "other_action"}
        )

        event = CloudEvent(
            specversion="1.0",
            id="test-123",
            source="/test",
            type="test.event",
            data=payload,
        )

        context = {}
        assert await handler._can_handle(event, context) is False

    @pytest.mark.asyncio
    async def test_handle_sets_context_for_agent(self):
        """Ensures handler sets context flags for agent processing."""
        handler = AgentInvokerHandler()

        payload = CustomPayload(
            invoice_text="Test invoice text", details={"action": "invoke_agent"}
        )

        event = CloudEvent(
            specversion="1.0",
            id="test-123",
            source="/test",
            type="test.event",
            data=payload,
        )

        context = {}
        result = await handler._handle(event, context)

        # Handler should return None to pass to next handler
        assert result is None
        # But should set context flags
        assert context["use_agent"] is True
        assert context["agent_name"] == "AgentRuntime"
        assert context["invoice_text"] == "Test invoice text"


class TestSimpleProcessorHandler:
    """Tests for SimpleProcessorHandler - skipped as it requires line_items."""

    @pytest.mark.skip(
        reason="SimpleProcessorHandler expects line_items which CustomPayload doesn't have"
    )
    async def test_placeholder(self):
        pass


class TestProcessingHandler:
    """Tests for ProcessingHandler."""

    @pytest.mark.asyncio
    async def test_can_handle_after_validation(self):
        """Ensures ProcessingHandler runs after validation."""
        handler = ProcessingHandler()

        event = MagicMock(spec=CloudEvent)
        event.data = {"key": "value"}

        # Should not handle without validation
        context = {}
        assert await handler._can_handle(event, context) is False

        # Should handle after validation
        context["validated_at"] = "timestamp"
        assert await handler._can_handle(event, context) is True

    @pytest.mark.asyncio
    async def test_handle_enriches_payload(self):
        """Ensures ProcessingHandler enriches the payload."""
        handler = ProcessingHandler()

        payload = CustomPayload(invoice_text="Test invoice", details={})

        event = CloudEvent(
            specversion="1.0",
            id="test-789",
            source="/test",
            type="test.event",
            data=payload,
        )

        context = {"validated_at": "timestamp"}
        result = await handler._handle(event, context)

        # Handler should return enriched result
        assert result is not None
        assert result["status"] == "processed"
        assert result["processed_by"] == [handler.name]
        assert "transformed_payload" in context
