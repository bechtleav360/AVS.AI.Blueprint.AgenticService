"""Pytest configuration for unit tests."""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def mock_prompt_loader(request):
    """Mock PromptLoader.load_prompt to avoid file I/O in tests, except for PromptLoader tests and test_build_requires_system_prompt."""
    skip_nodes = (
        "test_prompt_loader",
        "test_build_requires_system_prompt",
        "test_build_resolves_prompt_from_config",
        "test_build_constructs_runtime_with_full_configuration",
    )

    # Don't mock for specific tests that provide their own patching behavior
    if any(marker in request.node.nodeid for marker in skip_nodes):
        yield None
        return

    with patch("blueprint.agents.agent.agent_builder.PromptLoader.load_prompt") as mock_load:
        mock_load.return_value = "Test prompt"
        yield mock_load
