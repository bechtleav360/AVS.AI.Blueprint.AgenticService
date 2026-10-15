"""Declaration of the document summarizer agent.

``agent`` records what the agent is made of; nothing is constructed until it is built.
``create_app()`` builds it as an application of its own::

    uvicorn src.main:create_app --factory
"""

from pathlib import Path

from pydantic_ai import Tool

from blueprint.agents import AgentBuilder, AppBuilder, Config
from src.api.routes import SummarizerApi
from src.models.schemas import DocumentSummary
from src.services.summarizer_service import SummarizerService
from src.tools.text_tools import extract_metadata, word_count

document_summarizer = (
    AgentBuilder(runtime_name="document_summarizer", package_root=Path(__file__).parent)
    .with_model_from_config()
    .with_system_prompt("system")
    .with_tools(
        [
            Tool(name="word_count", function=word_count),
            Tool(name="extract_metadata", function=extract_metadata),
        ]
    )
    .with_result_type(DocumentSummary)
)

agent = (
    AppBuilder()
    .with_service(SummarizerService)
    .with_agent(document_summarizer, name="document_summarizer")
    .with_rest_api(SummarizerApi)
    .with_cache()
)


def create_app():
    """Build this agent as an application of its own."""
    return agent.build(Config(settings_files=["settings.toml", "secrets.toml"], root_path=str(Path(__file__).parent.parent)))
