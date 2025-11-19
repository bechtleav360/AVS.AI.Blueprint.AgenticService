"""Main entry point for the trivia game."""

from pathlib import Path

from blueprint.agents.agent import AgentBuilder
from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config
from pydantic_ai import Agent
from .api import TriviaGameRestApi

# Define the project root and paths to configuration files
project_root = Path(__file__).parent.parent
settings_files = [
    project_root / "settings.toml",
    project_root / "secrets.toml",
]

# ============================================================================
# Step 1: Build Trivia Game Agent
# ============================================================================

# Load configuration
config = Config(settings_files=settings_files, root_path=project_root)

# Build trivia master agent
trivia_agent: Agent = (
    AgentBuilder(config, runtime_name="trivia_master")
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

app = AppBuilder(settings_files=settings_files, root_path=project_root).with_agent(trivia_agent).with_rest_api(trivia_api).build()
