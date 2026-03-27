"""Main entry point for the trivia game."""

from pathlib import Path

from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from pydantic_ai import Agent

from .services.trivia_service import TriviaService
from .api import TriviaGameRestApi

# ============================================================================
# Step 1: Build Trivia Game Agent
# ============================================================================

# Load configuration
config = Config(
    settings_files=[
        "settings.toml",
        "secrets.toml",
    ],
    root_path=Path(__file__).parent.parent,
)

# Build trivia master agent with package_root for prompt discovery
trivia_agent: Agent = (
    AgentBuilder(config, runtime_name="trivia_master")
    .with_model_from_config("trivia_master")
    .with_system_prompt("system")
    .build(name="trivia_master")
)

# ============================================================================
# Step 2: Build App and Register Agent
# ============================================================================

app = (
    AppBuilder(config=config).with_cache().with_agent(trivia_agent).with_service(TriviaService()).with_rest_api(TriviaGameRestApi()).build()
)
