"""Application entry point for the Order Event Pipeline."""

from blueprint.agents import AppBuilder, Config

from .handlers.order_validation_handler import OrderValidationHandler
from .handlers.order_enrichment_handler import OrderEnrichmentHandler
from .services.order_service import OrderService
from .api.routes import OrderApi

config = Config(settings_files=["settings.toml"])

app = (
    AppBuilder(config)
    .with_service(OrderService)
    .with_handler(OrderValidationHandler)
    .with_handler(OrderEnrichmentHandler)
    .with_rest_api(OrderApi)
    .with_cache()
    .build()
)
