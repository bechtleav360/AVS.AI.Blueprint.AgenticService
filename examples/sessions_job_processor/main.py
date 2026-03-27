"""Main entry point for sessions job processor example.

This example demonstrates how to use the Blueprint Agents framework to consume
and process jobs from the sessions service via SSE.
"""

import logging
from pathlib import Path

import uvicorn

from blueprint.agents import AppBuilder, Config
from handlers.text_extraction_handler import TextExtractionHandler

logger = logging.getLogger(__name__)


def create_app():
    """Create and configure the FastAPI application."""
    # Load configuration
    config = Config(
        settings_files=["settings.toml"],
        root_path=Path(__file__).parent,
    )

    # Build application with handler
    app = (
        AppBuilder(config)
        .with_handler(TextExtractionHandler())
        .build()
    )

    logger.info("Sessions job processor application created")
    return app


if __name__ == "__main__":
    app = create_app()

    # Run with uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
