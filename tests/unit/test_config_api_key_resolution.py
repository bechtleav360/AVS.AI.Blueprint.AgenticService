"""Unit tests for API key configuration resolution.

This test suite validates that the configuration system correctly loads
and resolves API keys for different runtimes.
"""

from pathlib import Path

import pytest

from blueprint.agents.agent.agent_builder import AgentBuilder
from blueprint.agents.config import Config


class TestAPIKeyResolution:
    """Test suite for API key resolution with runtime-specific overrides."""

    @pytest.fixture
    def settings_file(self) -> Path:
        """Return path to the test settings file."""
        return Path(__file__).parent / "fixtures" / "settings_api_key_test.toml"

    def test_global_api_key_loaded_from_settings(self, settings_file: Path) -> None:
        """Test that global API key is loaded from settings file."""
        config = Config(
            settings_files=[str(settings_file)],
            root_path=settings_file.parent,
        )

        assert config.get("model_api_key") == "vllm-global-key-12345"
        assert config.get("model_provider") == "vllm"

    def test_runtime_specific_settings_accessible(self, settings_file: Path) -> None:
        """Test that runtime-specific settings are accessible from settings."""
        config = Config(
            settings_files=[str(settings_file)],
            root_path=settings_file.parent,
        )

        evaluator_settings = config.settings.get("runtimes.evaluator")
        assert evaluator_settings is not None
        assert evaluator_settings.get("model_provider") == "openai"
        assert evaluator_settings.get("model_api_key") == "openai-evaluator-key-67890"

    def test_search_runtime_settings_accessible(self, settings_file: Path) -> None:
        """Test that search runtime settings are accessible."""
        config = Config(
            settings_files=[str(settings_file)],
            root_path=settings_file.parent,
        )

        search_settings = config.settings.get("runtimes.search")
        assert search_settings is not None
        assert search_settings.get("model_provider") == "vllm"
        assert search_settings.get("model_base_url") == "https://avs-embed.q14.net/v1"

    def test_multiple_runtimes_have_different_configurations(self, settings_file: Path) -> None:
        """Test that multiple runtimes can have different configurations."""
        config = Config(
            settings_files=[str(settings_file)],
            root_path=settings_file.parent,
        )

        evaluator = config.settings.get("runtimes.evaluator")
        assert evaluator.get("model_provider") == "openai"
        assert evaluator.get("model_api_key") == "openai-evaluator-key-67890"

        search = config.settings.get("runtimes.search")
        assert search.get("model_provider") == "vllm"
        assert search.get("model_base_url") == "https://avs-embed.q14.net/v1"

        assert evaluator.get("model_api_key") != search.get("model_api_key", config.get("model_api_key"))

    def test_global_defaults_are_available(self, settings_file: Path) -> None:
        """Test that global defaults are available for all runtimes."""
        config = Config(
            settings_files=[str(settings_file)],
            root_path=settings_file.parent,
        )

        assert config.get("model_provider") == "vllm"
        assert config.get("model_api_key") == "vllm-global-key-12345"
        assert config.get("model_base_url") == "https://avs-vllm.q14.net/v1"
        assert config.get("model_max_tokens") == 3000
        assert config.get("model_temperature") == 0.1

    def test_two_agents_with_different_runtime_configurations(self, settings_file: Path) -> None:
        """Test building two agents with different runtime configurations.

        This mimics real-world usage where:
        - Evaluator agent uses OpenAI (runtime-specific override)
        - Search agent uses vLLM (global default with runtime-specific base_url)
        """
        config = Config(
            settings_files=[str(settings_file)],
            root_path=settings_file.parent,
        )

        # Build evaluator agent with OpenAI configuration
        evaluator_builder = AgentBuilder(config, runtime_name="evaluator")
        evaluator_builder.with_model_from_config()
        evaluator_builder.with_system_prompt("You are an evaluator agent.")
        evaluator_agent = evaluator_builder.build()

        # Verify evaluator agent was built successfully
        assert evaluator_agent is not None
        assert evaluator_agent.model is not None

        # Get evaluator agent's current configuration from the Pydantic agent model
        evaluator_model = evaluator_agent.model
        assert evaluator_model.model_name is not None
        assert evaluator_model.model_name == "gpt-4"

        # Verify evaluator agent has correct AI configuration from agent runtime
        evaluator_agent_config = evaluator_agent.get_config()
        evaluator_ai_config = evaluator_agent_config.get_ai_config("evaluator")
        assert evaluator_ai_config.provider == "openai"
        assert evaluator_ai_config.api_key == "openai-evaluator-key-67890"
        assert evaluator_ai_config.model_name == "gpt-4"

        # Build search agent with vLLM configuration
        search_builder = AgentBuilder(config, runtime_name="search")
        search_builder.with_model_from_config()
        search_builder.with_system_prompt("You are a search agent.")
        search_agent = search_builder.build()

        # Verify search agent was built successfully
        assert search_agent is not None
        assert search_agent.model is not None

        # Get search agent's current configuration from the Pydantic agent model
        search_model = search_agent.model
        assert search_model.model_name is not None
        assert search_model.model_name == "embedding-model"

        # Verify search agent has correct AI configuration from agent runtime
        search_agent_config = search_agent.get_config()
        search_ai_config = search_agent_config.get_ai_config("search")
        assert search_ai_config.provider == "vllm"
        assert search_ai_config.base_url == "https://avs-embed.q14.net/v1"
        assert search_ai_config.model_name == "embedding-model"

        # Verify the two agents are different instances
        assert evaluator_agent is not search_agent
        assert evaluator_agent.model is not search_agent.model

        # Verify the two builders are different instances
        assert evaluator_builder is not search_builder
        assert evaluator_builder._runtime_name == "evaluator"
        assert search_builder._runtime_name == "search"

        # Verify configuration differences between agent runtimes
        assert evaluator_ai_config.provider != search_ai_config.provider
        assert evaluator_ai_config.api_key != search_ai_config.api_key
        assert evaluator_ai_config.model_name != search_ai_config.model_name

        # Verify evaluator uses OpenAI while search uses vLLM
        assert evaluator_ai_config.provider == "openai"
        assert search_ai_config.provider == "vllm"
