"""Generic unit tests for placeholder agent tools in `custom.src.agent.tools`."""

from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext

from custom.src.agent.tools import Tools
from custom.src.models.processing import ProcessingContext
from custom.src.models.resource import ResourceInput
from custom.src.models.results import CustomAgentOutput


@pytest.fixture
def mock_run_context():
    """Provides a mock RunContext for tool tests."""
    ctx = MagicMock(spec=RunContext)
    ctx.deps = MagicMock(spec=ProcessingContext)
    ctx.deps.correlation_id = "550e8400-e29b-41d4-a716-446655440000"
    ctx.deps.event_id = "550e8400-e29b-41d4-a716-446655440001"
    return ctx


@pytest.fixture
def sample_resource_input():
    """Provides a sample ResourceInput model for tool tests."""
    return ResourceInput(
        id="test-resource-123",
        tags={"service-type": "database"},
        properties={"is_serverless": False},
        attributes={"encryption_enabled": True},
    )


class TestGenericTools:
    """Tests for the placeholder Tools class to ensure its interface is stable."""

    @pytest.mark.asyncio
    async def test_analyze_resource_tool_calls_logic_and_returns_output(
        self, mock_run_context, sample_resource_input
    ):
        """Ensures the analyze_resource tool calls the business logic and returns a CustomAgentOutput."""
        # Instantiate the tool and execute
        tools = Tools()
        result = await tools.analyze_resource(mock_run_context, sample_resource_input)

        # Verify that the output is correctly structured
        assert isinstance(result, CustomAgentOutput)
        assert result.resource_id == "test-resource-123"
        assert result.status in ["compliant", "non_compliant"]
        assert isinstance(result.confidence, float)
        assert isinstance(result.recommendations, list)
        assert all(isinstance(rec, str) for rec in result.recommendations)
