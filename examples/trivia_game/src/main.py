"""Main entry point for the trivia game."""

from pathlib import Path

from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from pydantic_ai import Agent
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
    AgentBuilder(config, runtime_name="trivia_master", package_root=Path(__file__).parent)
    .with_model_from_config("trivia_master")
    .with_system_prompt_file("system")
    .with_prompt("evaluate_answer")
    .with_prompt("generate_question")
    .build(name="trivia_master")
)

# ============================================================================
# Step 2: Build App and Register Agent
# ============================================================================

# Create the Trivia Game REST API instance
trivia_api = TriviaGameRestApi()

app = AppBuilder(config=config).with_agent(trivia_agent).with_rest_api(trivia_api).build()
