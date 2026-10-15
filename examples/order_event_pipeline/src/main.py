"""Declaration of the Order Event Pipeline agent.

``agent`` records what the agent is made of; nothing is constructed until it is built.
``create_app()`` builds it as an application of its own::

    uvicorn src.main:create_app --factory
"""

from pathlib import Path

from blueprint.agents import AppBuilder, Config

from .api.routes import OrderApi
from .handlers.order_enrichment_handler import OrderEnrichmentHandler
from .handlers.order_validation_handler import OrderValidationHandler
from .services.order_service import OrderService

agent = (
    AppBuilder()
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_handler(OrderEnrichmentHandler)
    .with_rest_api(OrderApi)
    .with_cache()
)


def create_app():
    """Build this agent as an application of its own."""
    return agent.build(Config(settings_files=["settings.toml"], root_path=str(Path(__file__).parent.parent)))
