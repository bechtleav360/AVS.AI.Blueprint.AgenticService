"""Declaration of the site readings agent.

``agent`` records what the agent is made of; nothing is constructed until it is built.
``create_app()`` builds it as an application of its own::

    uvicorn src.main:create_app --factory

Nothing here mentions the sites: the connections come from ``nats_connection_source`` in
``settings.toml``, which the process reads, not the agent.
"""

from pathlib import Path

from blueprint.agents import AppBuilder, Config

from .api.routes import AlertApi
from .handlers.reading_handler import ReadingHandler
from .services.reading_service import ReadingService

agent = AppBuilder().with_service(ReadingService).with_handler(ReadingHandler).with_rest_api(AlertApi).with_cache()


def create_app():
    """Build this agent as an application of its own."""
    return agent.build(Config(settings_files=["settings.toml"], root_path=str(Path(__file__).parent.parent)))
