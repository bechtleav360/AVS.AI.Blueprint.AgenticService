"""Application entry point for the Inventory API."""

from blueprint.agents import AppBuilder, Config

from src.api.routes import InventoryApi
from src.services.inventory_service import InventoryService

config = Config(settings_files=["settings.toml"])

app = AppBuilder(config).with_service(InventoryService).with_rest_api(InventoryApi()).with_cache().build()
