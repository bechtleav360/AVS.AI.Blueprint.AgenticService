"""Generic unit tests for placeholder event handlers in `custom.src.agent.handlers`."""

from unittest.mock import MagicMock

import pytest
from base.src.models.events import CloudEvent

from custom.src.agent.handlers import ProcessingHandler, CustomHandler, get_all_handlers


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


class TestGenericHandlers:
    """Tests for the placeholder handlers to ensure the chain-of-responsibility is intact."""

    @pytest.mark.asyncio
    async def test_validation_handler_can_handle_any_event(
        self, mock_event, mock_context
    ):
        """Ensures the default ValidationHandler always runs."""
        handler = CustomHandler()
        assert await handler._can_handle(mock_event, mock_context) is True

    @pytest.mark.asyncio
    async def test_validation_handler_passes_with_data(self, mock_event, mock_context):
        """Ensures the ValidationHandler returns None to continue the chain when data is present."""
        handler = CustomHandler()
        result = await handler._handle(mock_event, mock_context)
        assert result is None
        assert "validated_at" in mock_context

    @pytest.mark.asyncio
    async def test_validation_handler_fails_without_data(
        self, mock_event, mock_context
    ):
        """Ensures the ValidationHandler returns a result to stop the chain if data is missing."""
        handler = CustomHandler()
        mock_event.data = None
        result = await handler._handle(mock_event, mock_context)
        assert isinstance(result, dict)
        assert result["status"] == "validation_failed"

    @pytest.mark.asyncio
    async def test_processing_handler_can_handle_after_validation(
        self, mock_event, mock_context
    ):
        """Ensures the ProcessingHandler runs only after the ValidationHandler."""
        handler = ProcessingHandler()
        # Should not handle if validation has not run
        assert await handler._can_handle(mock_event, mock_context) is False

        # Should handle after validation
        mock_context["validated_at"] = "timestamp"
        assert await handler._can_handle(mock_event, mock_context) is True

    @pytest.mark.asyncio
    async def test_processing_handler_handle_returns_none(
        self, mock_event, mock_context
    ):
        """Ensures the placeholder ProcessingHandler returns None."""
        handler = ProcessingHandler()
        result = await handler._handle(mock_event, mock_context)
        assert result is None

    def test_get_all_handlers_returns_list_of_handlers(self):
        """Ensures the handler registration function returns a list of EventHandler instances."""
        handlers = get_all_handlers()
        assert isinstance(handlers, list)
        assert len(handlers) > 0
        assert isinstance(handlers[0], CustomHandler)
        assert isinstance(handlers[1], ProcessingHandler)
