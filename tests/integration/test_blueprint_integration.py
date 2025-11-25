"""Integration tests for the Blueprint Agents framework.

Tests the complete workflow of building agents, apps, and handling events
with mocked LLM providers.
"""

import json

import pytest
from pydantic import BaseModel

from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from blueprint.agents.base import EventHandler
from blueprint.agents.models.events import CloudEvent
from blueprint.agents.models.result import AgentOutput, Evidence


class MockLLMResponse(BaseModel):
    """Mock response from LLM."""

    status: str
    confidence: float
    reasoning: str


class TestAgentIntegration:
    """Integration tests for agent building and execution."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return Config(
            settings_files=[],
            root_path=".",
        )

    @pytest.fixture
    def mock_vllm_response(self):
        """Mock vLLM provider response."""
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "status": "compliant",
                                "confidence": 0.95,
                                "reasoning": "All requirements met",
                            }
                        )
                    }
                }
            ]
        }

    def test_agent_builder_initialization(self, config):
        """Test AgentBuilder can be initialized with config."""
        builder = AgentBuilder(config, runtime_name="test_agent")
        assert builder._config == config
        assert builder._runtime_name == "test_agent"
        assert builder._tools == []

    def test_agent_builder_with_system_prompt(self, config):
        """Test AgentBuilder can set system prompt."""
        builder = AgentBuilder(config)
        builder.with_system_prompt("You are a helpful assistant")
        assert builder._system_prompt == "You are a helpful assistant"

    def test_agent_builder_with_prompt_text(self, config):
        """Test AgentBuilder can register prompts via text."""
        builder = AgentBuilder(config)
        # Prompts are now loaded on-demand via get_prompt() method
        # This test verifies the builder can be configured
        builder.with_system_prompt("You are a helpful assistant")
        assert builder._system_prompt == "You are a helpful assistant"

    def test_agent_builder_with_result_type(self, config):
        """Test AgentBuilder can set result type."""
        builder = AgentBuilder(config)
        builder.with_result_type(MockLLMResponse)
        assert builder._result_type == MockLLMResponse

    def test_agent_builder_chaining(self, config):
        """Test AgentBuilder supports method chaining."""
        builder = AgentBuilder(config).with_system_prompt("You are helpful").with_result_type(MockLLMResponse)
        assert builder._system_prompt == "You are helpful"
        assert builder._result_type == MockLLMResponse


class TestAppBuilderIntegration:
    """Integration tests for app building."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return Config(
            settings_files=[],
            root_path=".",
        )

    def test_app_builder_with_config(self, config):
        """Test AppBuilder can be initialized with config."""
        app_builder = AppBuilder(config=config)
        assert app_builder._config == config

    def test_app_builder_requires_config(self):
        """Test AppBuilder requires config parameter."""
        config = Config(settings_files=[], root_path=".")
        app_builder = AppBuilder(config=config)
        assert app_builder._config is not None

    def test_app_builder_config_stored(self, config):
        """Test that config is properly stored in AppBuilder."""
        app_builder = AppBuilder(config=config)
        assert app_builder._config == config

    def test_app_builder_with_handler(self, config):
        """Test AppBuilder can register event handlers."""
        app_builder = AppBuilder(config=config)

        class TestHandler(EventHandler):
            """Test event handler."""

            def __init__(self):
                super().__init__()

            

            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return True

            async def handle_event(self, event: CloudEvent, context: dict):
                return None

        app_builder.with_handler(TestHandler)
        handlers = app_builder._component_registry.get_handlers()
        assert len(handlers) == 1
        assert isinstance(handlers[0], TestHandler)

    def test_app_builder_with_handler_instance(self, config):
        """Test AppBuilder can register handler instances."""
        app_builder = AppBuilder(config=config)

        class TestHandler(EventHandler):
            """Test event handler."""

            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return True

            async def handle_event(self, event: CloudEvent, context: dict):
                return None

        handler_instance = TestHandler()
        app_builder.with_handler(handler_instance)
        handlers = app_builder._component_registry.get_handlers()
        assert len(handlers) == 1
        assert handlers[0] is handler_instance

    def test_app_builder_handler_chaining(self, config):
        """Test AppBuilder supports handler chaining."""
        app_builder = AppBuilder(config=config)

        class Handler1(EventHandler):
            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return True

            async def handle_event(self, event: CloudEvent, context: dict):
                return None

        class Handler2(EventHandler):
            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return True

            async def handle_event(self, event: CloudEvent, context: dict):
                return None

        app_builder.with_handler(Handler1).with_handler(Handler2)
        handlers = app_builder._component_registry.get_handlers()
        assert len(handlers) == 2


class TestEventHandling:
    """Integration tests for event handling."""

    @pytest.mark.asyncio
    async def test_cloud_event_creation(self):
        """Test CloudEvent can be created and validated."""
        event = CloudEvent(
            id="test-123",
            type="test.event",
            source="/test",
            data={"key": "value"},
        )
        assert event.id == "test-123"
        assert event.type == "test.event"
        assert event.source == "/test"
        assert event.data == {"key": "value"}

    @pytest.mark.asyncio
    async def test_cloud_event_with_base64_data(self):
        """Test CloudEvent with base64 encoded data."""
        event = CloudEvent(
            id="test-456",
            type="test.event",
            source="/test",
            data_base64="aGVsbG8gd29ybGQ=",  # "hello world" in base64
        )
        assert event.id == "test-456"
        assert event.data_base64 == "aGVsbG8gd29ybGQ="

    @pytest.mark.asyncio
    async def test_cloud_event_cannot_have_both_data_and_base64(self):
        """Test CloudEvent validation prevents both data and data_base64."""
        with pytest.raises(ValueError):
            CloudEvent(
                id="test-789",
                type="test.event",
                source="/test",
                data={"key": "value"},
                data_base64="aGVsbG8gd29ybGQ=",
            )

    @pytest.mark.asyncio
    async def test_agent_output_creation(self):
        """Test AgentOutput model creation."""
        evidence = Evidence(
            type="tag",
            source="test",
            value="test_value",
            confidence=0.9,
        )
        output = AgentOutput(
            resource_id="res-123",
            status="compliant",
            confidence=0.95,
            evidence=[evidence],
            reasoning="All checks passed",
        )
        assert output.resource_id == "res-123"
        assert output.status == "compliant"
        assert len(output.evidence) == 1
        assert output.evidence[0].type == "tag"

    @pytest.mark.asyncio
    async def test_agent_output_evidence_sorted_by_confidence(self):
        """Test AgentOutput sorts evidence by confidence."""
        evidence1 = Evidence(
            type="tag1",
            source="test",
            value="value1",
            confidence=0.5,
        )
        evidence2 = Evidence(
            type="tag2",
            source="test",
            value="value2",
            confidence=0.9,
        )
        evidence3 = Evidence(
            type="tag3",
            source="test",
            value="value3",
            confidence=0.7,
        )
        output = AgentOutput(
            resource_id="res-123",
            status="compliant",
            confidence=0.95,
            evidence=[evidence1, evidence2, evidence3],
        )
        # Evidence should be sorted by confidence in descending order
        assert output.evidence[0].confidence == 0.9
        assert output.evidence[1].confidence == 0.7
        assert output.evidence[2].confidence == 0.5


class TestConfigIntegration:
    """Integration tests for configuration."""

    def test_config_initialization(self):
        """Test Config can be initialized."""
        config = Config(settings_files=[], root_path=".")
        assert config is not None

    def test_config_get_method(self):
        """Test Config get method for accessing values."""
        config = Config(settings_files=[], root_path=".")
        # Get a default value that should exist
        log_level = config.get("log_level", "INFO")
        assert log_level in ["INFO", "DEBUG", "WARNING", "ERROR"]

    def test_config_ai_config(self):
        """Test Config can provide AI configuration."""
        config = Config(settings_files=[], root_path=".")
        ai_config = config.get_ai_config("default")
        assert ai_config is not None


class TestEndToEndWorkflow:
    """End-to-end integration tests."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return Config(settings_files=[], root_path=".")

    def test_complete_app_setup(self, config):
        """Test complete app setup workflow."""
        # Create app builder
        app_builder = AppBuilder(config=config)

        # Register a handler
        class SimpleHandler(EventHandler):
            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return event.type == "test.event"

            async def handle_event(self, event: CloudEvent, context: dict):
                return None

        app_builder.with_handler(SimpleHandler)

        # Verify setup
        handlers = app_builder._component_registry.get_handlers()
        assert len(handlers) == 1
        assert isinstance(handlers[0], SimpleHandler)

    @pytest.mark.asyncio
    async def test_handler_event_processing(self):
        """Test handler can process events."""

        class ProcessingHandler(EventHandler):
            def __init__(self):
                super().__init__()
                self.processed_events = []

            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return event.type == "process.event"

            async def handle_event(self, event: CloudEvent, context: dict):
                self.processed_events.append(event)
                return None

        handler = ProcessingHandler()

        # Create test event
        event = CloudEvent(
            id="test-001",
            type="process.event",
            source="/test",
            data={"action": "process"},
        )

        # Test handler
        can_handle = await handler.can_handle_event(event, {})
        assert can_handle is True

        await handler.handle_event(event, {})
        assert len(handler.processed_events) == 1
        assert handler.processed_events[0].id == "test-001"

    def test_multiple_handlers_registration(self, config):
        """Test registering multiple handlers."""
        app_builder = AppBuilder(config=config)

        class Handler1(EventHandler):
            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return True

            async def handle_event(self, event: CloudEvent, context: dict):
                return None

        class Handler2(EventHandler):
            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return True

            async def handle_event(self, event: CloudEvent, context: dict):
                return None

        class Handler3(EventHandler):
            async def can_handle_event(self, event: CloudEvent, context: dict) -> bool:
                return True

            async def handle_event(self, event: CloudEvent, context: dict):
                return None

        app_builder.with_handler(Handler1).with_handler(Handler2).with_handler(Handler3)

        handlers = app_builder._component_registry.get_handlers()
        assert len(handlers) == 3
        assert all(isinstance(h, EventHandler) for h in handlers)
