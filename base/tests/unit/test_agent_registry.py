"""Unit tests for AgentRegistry."""

from unittest.mock import Mock

import pytest

from base.src.registry import AgentRegistry


class TestAgentRegistry:
    """Test suite for AgentRegistry."""

    @pytest.fixture
    def registry(self):
        """Create AgentRegistry instance."""
        return AgentRegistry()

    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent."""
        agent = Mock()
        agent.name = "test_agent"
        return agent

    def test_registry_initialization(self):
        """Test AgentRegistry can be initialized."""
        registry = AgentRegistry()

        assert registry._agents == {}

    def test_register_agent(self, registry, mock_agent):
        """Test registering an agent."""
        registry.register("test_agent", mock_agent)

        assert "test_agent" in registry._agents
        assert registry._agents["test_agent"] == mock_agent

    def test_register_duplicate_agent_raises_error(self, registry, mock_agent):
        """Test registering duplicate agent name raises error."""
        registry.register("test_agent", mock_agent)

        with pytest.raises(ValueError, match="already registered"):
            registry.register("test_agent", mock_agent)

    def test_get_agent(self, registry, mock_agent):
        """Test getting a registered agent."""
        registry.register("test_agent", mock_agent)

        result = registry.get("test_agent")

        assert result == mock_agent

    def test_get_nonexistent_agent_raises_error(self, registry):
        """Test getting non-existent agent raises error."""
        with pytest.raises(ValueError, match="not found"):
            registry.get("nonexistent")

    def test_get_error_shows_available_agents(self, registry, mock_agent):
        """Test error message shows available agents."""
        registry.register("agent1", mock_agent)
        registry.register("agent2", mock_agent)

        with pytest.raises(ValueError, match="agent1, agent2"):
            registry.get("nonexistent")

    def test_get_error_shows_none_when_empty(self, registry):
        """Test error message shows 'none' when no agents registered."""
        with pytest.raises(ValueError, match="none"):
            registry.get("nonexistent")

    def test_has_agent_returns_true_when_exists(self, registry, mock_agent):
        """Test has() returns True for existing agent."""
        registry.register("test_agent", mock_agent)

        assert registry.has("test_agent") is True

    def test_has_agent_returns_false_when_not_exists(self, registry):
        """Test has() returns False for non-existent agent."""
        assert registry.has("nonexistent") is False

    def test_list_agents_returns_all_names(self, registry, mock_agent):
        """Test list_agents returns all registered agent names."""
        registry.register("agent1", mock_agent)
        registry.register("agent2", mock_agent)
        registry.register("agent3", mock_agent)

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
        registry.register("agent1", mock_agent)
        registry.register("agent2", mock_agent)

        registry.clear()

        assert len(registry._agents) == 0
        assert registry.list_agents() == []

    def test_register_multiple_agents(self, registry):
        """Test registering multiple different agents."""
        agent1 = Mock()
        agent2 = Mock()
        agent3 = Mock()

        registry.register("agent1", agent1)
        registry.register("agent2", agent2)
        registry.register("agent3", agent3)

        assert registry.get("agent1") == agent1
        assert registry.get("agent2") == agent2
        assert registry.get("agent3") == agent3

    def test_registry_is_case_sensitive(self, registry, mock_agent):
        """Test agent names are case-sensitive."""
        registry.register("TestAgent", mock_agent)

        assert registry.has("TestAgent") is True
        assert registry.has("testagent") is False

    def test_clear_allows_re_registration(self, registry, mock_agent):
        """Test agents can be re-registered after clear."""
        registry.register("test_agent", mock_agent)
        registry.clear()

        # Should not raise error
        registry.register("test_agent", mock_agent)

        assert registry.get("test_agent") == mock_agent
