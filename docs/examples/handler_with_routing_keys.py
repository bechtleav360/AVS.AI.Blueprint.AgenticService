"""Example handler demonstrating event type declaration.

This example shows how handlers declare which event types they publish.
The mapping to topics and routing keys is configured in values.yaml.
"""

import logging
from typing import Any, Optional, Tuple

from base.src.handler import EventHandler
from base.src.models import CloudEvent

logger = logging.getLogger(__name__)


class InvoiceProcessorHandler(EventHandler):
    """Example handler that processes invoices with custom event routing."""

    def __init__(self) -> None:
        super().__init__("InvoiceProcessorHandler", priority=10)

    async def can_handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> bool:
        """Handle invoice processing events."""
        return event.type == "invoice.received"

    async def handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> Optional[Any]:
        """Process the invoice."""
        logger.info("Processing invoice event")

        # Your business logic here
        invoice_data = event.data
        context["invoice_id"] = invoice_data.get("invoice_id")
        context["amount"] = invoice_data.get("amount")

        # Return None to continue to agent processing
        return None

    def get_runtime_name(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> Optional[str]:
        """Use the invoice analyzer runtime."""
        return "invoice_analyzer"

    def get_published_event_types(self) -> Optional[Tuple[str, str]]:
        """Declare the event types this handler publishes.

        Returns tuple of (success_event_type, error_event_type).
        The mapping to topics and routing keys is configured in values.yaml:

        eventPublishing:
          topicMapping:
            "agent.output.invoice.processed":
              topic: "invoice.events"
              routing_key: "invoice.processed.success"
            "agent.error.invoice.processing":
              topic: "invoice.errors"
              routing_key: "invoice.error.processing"
        """
        return (
            "agent.output.invoice.processed",
            "agent.error.invoice.processing",
        )


class DocumentClassifierHandler(EventHandler):
    """Example handler for document classification with different routing."""

    def __init__(self) -> None:
        super().__init__("DocumentClassifierHandler", priority=20)

    async def can_handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> bool:
        """Handle document classification events."""
        return event.type == "document.uploaded"

    async def handle_event(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> Optional[Any]:
        """Classify the document."""
        logger.info("Classifying document")

        # Your business logic here
        document_data = event.data
        context["document_id"] = document_data.get("document_id")
        context["document_type"] = document_data.get("type")

        return None

    def get_runtime_name(
        self, event: CloudEvent, context: dict[str, Any]
    ) -> Optional[str]:
        """Use the document classifier runtime."""
        return "document_classifier"

    def get_published_event_types(self) -> Optional[Tuple[str, str]]:
        """Declare the event types this handler publishes.

        Returns tuple of (success_event_type, error_event_type).
        Configure routing in values.yaml:

        eventPublishing:
          topicMapping:
            "agent.output.document.classified":
              topic: "document.events"
              routing_key: "document.classified"
            "agent.error.document.classification":
              topic: "document.errors"
              routing_key: "document.error.classification"
        """
        return (
            "agent.output.document.classified",
            "agent.error.document.classification",
        )
