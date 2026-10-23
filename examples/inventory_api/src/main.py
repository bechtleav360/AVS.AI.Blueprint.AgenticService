"""Declaration of the Inventory API agent.

``agent`` records what the agent is made of; nothing is constructed until it is built.
``create_app()`` builds it as an application of its own::

    uvicorn src.main:create_app --factory
"""

from pathlib import Path

from blueprint.agents import AppBuilder, Config

from src.api.routes import InventoryApi
from src.services.inventory_service import InventoryService

agent = AppBuilder().with_service(InventoryService).with_rest_api(InventoryApi).with_cache()


def create_app():
    """Build this agent as an application of its own."""
    return agent.build(Config(settings_files=["settings.toml"], root_path=str(Path(__file__).parent.parent)))
