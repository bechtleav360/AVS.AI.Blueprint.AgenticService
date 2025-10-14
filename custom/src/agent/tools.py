"""Custom tools for the Pydantic AI agent (invoice processing)."""

import logging
from decimal import Decimal

from pydantic_ai import RunContext

from ..models import InvoiceAnalysisOutput, InvoiceInput, ProcessingContext
from ..services import InvoiceProcessingLogic

logger = logging.getLogger(__name__)


class Tools:
    """
    Encapsulates deterministic business logic that the agent can invoke as tools.

    This keeps core rules testable and efficient while allowing the LLM to
    orchestrate and explain results.
    """

    async def calculate_invoice(self, ctx: RunContext[ProcessingContext], invoice: InvoiceInput) -> InvoiceAnalysisOutput:
        """
        Calculate invoice totals and infer taxes deterministically.

        Returns an InvoiceAnalysisOutput with computed totals and tax amounts.
        """
        logger.info("Executing calculate_invoice tool for invoice %s", invoice.invoice_id)

        invoice_dict = invoice.model_dump()
        calculation = InvoiceProcessingLogic.calculate_invoice(invoice_dict)
        recommendations = InvoiceProcessingLogic.generate_recommendations(calculation, invoice_dict)

        status = calculation.get("status", "unknown")
        total_amount = calculation.get("total_amount", Decimal("0.00"))
        inferred_tax = calculation.get("inferred_tax_amount", Decimal("0.00"))
        confidence = calculation.get("confidence", 0.0)

        summary = (
            f"Invoice {invoice.invoice_id} processed: total {total_amount} {invoice.currency}, "
            f"inferred tax {inferred_tax} {invoice.currency}."
        )

        notes = None
        if not calculation.get("evidence"):
            notes = "No calculation evidence; review line items."

        return InvoiceAnalysisOutput(
            invoice_id=invoice.invoice_id,
            status=status,
            summary=summary,
            total_amount=total_amount,
            inferred_tax_amount=inferred_tax,
            confidence=confidence,
            notes=notes,
            metadata={
                "currency": invoice.currency,
                "line_item_count": len(invoice.line_items),
                "evidence": calculation.get("evidence", []),
                "recommendations": recommendations,
                "context": {
                    "correlation_id": (str(ctx.deps.correlation_id) if ctx.deps and ctx.deps.correlation_id else None),
                    "event_id": (str(ctx.deps.event_id) if ctx.deps and ctx.deps.event_id else None),
                },
            },
        )
