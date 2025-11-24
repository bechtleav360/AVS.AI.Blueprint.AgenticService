"""Unit tests for agent management in ComponentRegistry."""

from unittest.mock import Mock

import pytest

from blueprint.agents.config import Config
from blueprint.agents.registry import ComponentRegistry


class TestAgentRegistry:
    """Test suite for agent management in ComponentRegistry."""

    @pytest.fixture
    def config(self):
        """Create a mock Config instance."""
        config = Mock(spec=Config)
        return config

    @pytest.fixture
    def registry(self, config):
        """Create ComponentRegistry instance."""
        return ComponentRegistry(config)

    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent."""
        agent = Mock()
        agent.name = "test_agent"
        return agent

    def test_registry_initialization(self, config):
        """Test ComponentRegistry can be initialized."""
        registry = ComponentRegistry(config)

        assert registry._agents == {}

    def test_register_agent(self, registry, mock_agent):
        """Test registering an agent."""
        mock_agent.get_name.return_value = "test_agent"
        registry.register_agent(mock_agent)

        assert "test_agent" in registry._agents
        assert registry._agents["test_agent"] == mock_agent

    def test_register_duplicate_agent_raises_error(self, registry, mock_agent):
        """Test registering duplicate agent name raises error."""
        mock_agent.get_name.return_value = "test_agent"
        registry.register_agent(mock_agent)

        with pytest.raises(ValueError, match="already registered"):
            registry.register_agent(mock_agent)

    def test_get_agent(self, registry, mock_agent):
        """Test getting a registered agent."""
        mock_agent.get_name.return_value = "test_agent"
        registry.register_agent(mock_agent)

        result = registry.get_agent("test_agent")

        assert result == mock_agent

    def test_get_nonexistent_agent_raises_error(self, registry):
        """Test getting non-existent agent raises error."""
        with pytest.raises(ValueError, match="not found"):
            registry.get_agent("nonexistent")

    def test_get_error_shows_available_agents(self, registry, mock_agent):
        """Test error message shows available agents."""
        agent1 = Mock()
        agent1.get_name.return_value = "agent1"
        agent2 = Mock()
        agent2.get_name.return_value = "agent2"
        registry.register_agent(agent1)
        registry.register_agent(agent2)

        with pytest.raises(ValueError, match="agent1, agent2"):
            registry.get_agent("nonexistent")

    def test_get_error_shows_none_when_empty(self, registry):
        """Test error message shows 'none' when no agents registered."""
        with pytest.raises(ValueError, match="none"):
            registry.get_agent("nonexistent")

    def test_has_agent_returns_true_when_exists(self, registry, mock_agent):
        """Test has_agent() returns True for existing agent."""
        mock_agent.get_name.return_value = "test_agent"
        registry.register_agent(mock_agent)

        assert registry.has_agent("test_agent") is True

    def test_has_agent_returns_false_when_not_exists(self, registry):
        """Test has_agent() returns False for non-existent agent."""
        assert registry.has_agent("nonexistent") is False

    def test_list_agents_returns_all_names(self, registry, mock_agent):
        """Test list_agents returns all registered agent names."""
        agent1 = Mock()
        agent1.get_name.return_value = "agent1"
        agent2 = Mock()
        agent2.get_name.return_value = "agent2"
        agent3 = Mock()
        agent3.get_name.return_value = "agent3"
        registry.register_agent(agent1)
        registry.register_agent(agent2)
        registry.register_agent(agent3)

        names = registry.list_agents()

        assert len(names) == 3
        assert "agent1" in names
        assert "agent2" in names
        assert "agent3" in names

    def test_list_agents_returns_empty_list_when_none(self, registry):
        """Test list_agents returns empty list when no agents."""
        names = registry.list_agents()

        assert names == []

    def test_clear_removes_all_agents(self, registry, mock_agent):
        """Test clear removes all registered agents."""
        agent1 = Mock()
        agent1.get_name.return_value = "agent1"
        agent2 = Mock()
        agent2.get_name.return_value = "agent2"
        registry.register_agent(agent1)
        registry.register_agent(agent2)

        registry.clear()

        assert len(registry._agents) == 0
        assert registry.list_agents() == []

    def test_register_multiple_agents(self, registry):
        """Test registering multiple different agents."""
        agent1 = Mock()
        agent1.get_name.return_value = "agent1"
        agent2 = Mock()
        agent2.get_name.return_value = "agent2"
        agent3 = Mock()
        agent3.get_name.return_value = "agent3"

        registry.register_agent(agent1)
        registry.register_agent(agent2)
        registry.register_agent(agent3)

        assert registry.get_agent("agent1") == agent1
        assert registry.get_agent("agent2") == agent2
        assert registry.get_agent("agent3") == agent3

    def test_registry_is_case_sensitive(self, registry, mock_agent):
        """Test agent names are case-sensitive."""
        mock_agent.get_name.return_value = "TestAgent"
        registry.register_agent(mock_agent)

        assert registry.has_agent("TestAgent") is True
        assert registry.has_agent("testagent") is False

    def test_clear_allows_re_registration(self, registry, mock_agent):
        """Test agents can be re-registered after clear."""
        mock_agent.get_name.return_value = "test_agent"
        registry.register_agent(mock_agent)
        registry.clear()

        # Should not raise error
        registry.register_agent(mock_agent)

        assert registry.get_agent("test_agent") == mock_agent
