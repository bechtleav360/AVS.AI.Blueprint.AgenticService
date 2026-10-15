"""Declaration of the webhook relay agent.

``agent`` records what the agent is made of; nothing is constructed until it is built.
``create_app()`` builds it as an application of its own, with the settings next to ``src/``::

    uvicorn src.main:create_app --factory
"""

from __future__ import annotations

from pathlib import Path

from blueprint.agents import AppBuilder, Config

from .api.routes import WebhookApi
from .handlers.webhook_handler import WebhookHandler
from .services.webhook_service import WebhookService

agent = (
    AppBuilder()
    # Business service: deduplication, normalisation, filtering, enrichment
    .with_service(WebhookService)
    # One handler for webhook.received: translates, calls WebhookService.relay once
    .with_handler(WebhookHandler)
    # REST API
    .with_rest_api(WebhookApi)
    # Persistent cache for dedup and recent-event tracking
    .with_cache()
)


def create_app():
    """Build this agent as an application of its own."""
    return agent.build(Config(settings_files=["settings.toml"], root_path=str(Path(__file__).resolve().parent.parent)))
