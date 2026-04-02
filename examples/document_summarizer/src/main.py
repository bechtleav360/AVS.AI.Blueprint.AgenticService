"""Application entry point for the document summarizer service."""

from pathlib import Path

from pydantic_ai import Tool

from blueprint.agents import AppBuilder, AgentBuilder, Config
from src.models.schemas import DocumentSummary
from src.services.summarizer_service import SummarizerService
from src.api.routes import SummarizerApi
from src.tools.text_tools import word_count, extract_metadata

config = Config(
    settings_files=["settings.toml", "secrets.toml"],
    root_path=str(Path(__file__).parent.parent),
)

agent = (
    AgentBuilder(
        config,
        runtime_name="document_summarizer",
        package_root=Path(__file__).parent,
    )
    .with_model_from_config()
    .with_system_prompt("system")
    .with_tools(
        [
            Tool(name="word_count", function=word_count),
            Tool(name="extract_metadata", function=extract_metadata),
        ]
    )
    .with_result_type(DocumentSummary)
    .build()
)

app = (
    AppBuilder(config)
    .with_agent(agent)
    .with_service(SummarizerService)
    .with_rest_api(SummarizerApi())
    .with_cache()
    .build()
)
