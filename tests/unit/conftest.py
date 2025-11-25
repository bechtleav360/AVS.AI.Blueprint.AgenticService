"""Pytest configuration for unit tests."""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_prompt_loader(request):
    """Mock PromptLoader.load_prompt to avoid file I/O in tests, except for PromptLoader tests and test_build_requires_system_prompt."""
    # Don't mock for PromptLoader tests and test_build_requires_system_prompt
    if "test_prompt_loader" in request.node.nodeid or "test_build_requires_system_prompt" in request.node.nodeid:
        yield None
        return

    with patch("blueprint.agents.agent.agent_builder.PromptLoader.load_prompt") as mock_load:
        mock_load.return_value = "Test prompt"
        yield mock_load
