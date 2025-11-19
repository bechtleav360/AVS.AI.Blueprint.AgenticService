"""Tool implementations exposed to the agent runtime."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from custom.src.models.resource import InvoiceInput
from custom.src.services.invoice_services import InvoiceProcessingLogic


class AgentTools:
    """Collection of tools callable by the AI agent."""

    @staticmethod
    async def analyze_invoice(ctx: SimpleNamespace, invoice: InvoiceInput):
        """Invoke the invoice calculation logic using the shared runtime tools."""

        if ctx.deps is None:
            ctx.deps = SimpleNamespace()

        correlation_id = getattr(ctx.deps, "correlation_id", None)
        event_id = getattr(ctx.deps, "event_id", None)

        result = await InvoiceProcessingLogic.calculate_invoice_tool(ctx, invoice)
        result.metadata.setdefault("context", {})
        result.metadata["context"].update({
            "correlation_id": str(correlation_id) if isinstance(correlation_id, UUID) else correlation_id,
            "event_id": str(event_id) if isinstance(event_id, UUID) else event_id,
        })

        return result
