"""Tests for the simple event processor handler."""

import pytest
from blueprint.agents.models.events import CloudEvent

from examples.simple_event_processor.src.handlers import SimpleProcessorHandler


@pytest.fixture
def handler():
    """Create a handler instance."""
    return SimpleProcessorHandler("SimpleProcessorHandler")


@pytest.fixture
def sample_event():
    """Create a sample cloud event."""
    return CloudEvent(
        id="evt-123",
        type="data.received",
        specversion="1.0",
        source="test-source",
        data={"key1": "value1", "key2": "value2"},
    )


@pytest.fixture
def wrong_type_event():
    """Create an event with wrong type."""
    return CloudEvent(
        id="evt-456",
        type="data.ignored",
        specversion="1.0",
        source="test-source",
        data={"key": "value"},
    )


@pytest.mark.asyncio
async def test_can_handle_correct_event_type(handler, sample_event):
    """Test that handler can handle correct event type."""
    result = await handler.can_handle_event(sample_event, {})
    assert result is True


@pytest.mark.asyncio
async def test_cannot_handle_wrong_event_type(handler, wrong_type_event):
    """Test that handler cannot handle wrong event type."""
    result = await handler.can_handle_event(wrong_type_event, {})
    assert result is False


@pytest.mark.asyncio
async def test_handle_event_success(handler, sample_event):
    """Test successful event handling."""
    result = await handler.handle_event(sample_event, {})

    assert result.event_id == "evt-123"
    assert result.status == "success"
    assert "Successfully processed" in result.message
    assert result.error is None
    assert result.processed_data["original_data"] == {"key1": "value1", "key2": "value2"}
    assert result.processed_data["source"] == "test-source"
    assert result.processed_data["item_count"] == 2


@pytest.mark.asyncio
async def test_handle_event_with_empty_data(handler):
    """Test handling event with empty data."""
    event = CloudEvent(
        id="evt-empty",
        type="data.received",
        specversion="1.0",
        source="test-source",
        data={},
    )

    result = await handler.handle_event(event, {})

    assert result.event_id == "evt-empty"
    assert result.status == "success"
    assert result.processed_data["item_count"] == 0
