"""Application entry point -- wires all components via AppBuilder."""

from __future__ import annotations

from pathlib import Path

from blueprint.agents import AppBuilder, Config

from .api.routes import WebhookApi
from .handlers.content_filter import ContentFilter
from .handlers.metadata_enricher import MetadataEnricher
from .handlers.webhook_normalizer import WebhookNormalizer
from .services.webhook_service import WebhookService

# Load settings relative to this file so `uvicorn src.main:app` works from
# the example directory.
_HERE = Path(__file__).resolve().parent.parent

config = Config(
    settings_files=["settings.toml"],
    root_path=str(_HERE),
)

app = (
    AppBuilder(config)
    # Handler chain -- priority determines execution order (low first)
    .with_handler(WebhookNormalizer)   # priority 5  -- normalize
    .with_handler(ContentFilter)       # priority 10 -- filter
    .with_handler(MetadataEnricher)    # priority 15 -- enrich & publish
    # Business service
    .with_service(WebhookService)
    # REST API
    .with_rest_api(WebhookApi)
    # Persistent cache for dedup and recent-event tracking
    .with_cache()
    .build()
)
