"""Pure logic functions for invoice processing and tax calculation."""

from decimal import Decimal
from typing import Any


class InvoiceProcessingLogic:
    """
    Pure functions for invoice processing and tax calculation.

    This class contains stateless, pure functions that encapsulate invoice
    business logic. They can be tested independently of the agent/API.
    """

    @staticmethod
    def calculate_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
        """
        Calculate invoice totals and infer taxes.

        Args:
            invoice: The invoice data as a dictionary with line_items.

        Returns:
            A dictionary with total_amount, inferred_tax_amount, status, and evidence.
        """
        line_items = invoice.get("line_items", [])
        if not line_items:
            return {
                "total_amount": Decimal("0.00"),
                "inferred_tax_amount": Decimal("0.00"),
                "status": "incomplete",
                "evidence": ["No line items provided"],
                "confidence": 0.0,
            }

        total_net = Decimal("0.00")
        total_tax = Decimal("0.00")
        evidence = []
        tax_rates_found = []

        for idx, item in enumerate(line_items):
            quantity = Decimal(str(item.get("quantity", 0)))
            unit_price = Decimal(str(item.get("unit_price", 0)))
            tax_rate = item.get("tax_rate")

            line_net = quantity * unit_price
            total_net += line_net

            if tax_rate is not None:
                tax_rate_decimal = Decimal(str(tax_rate))
                line_tax = line_net * tax_rate_decimal
                total_tax += line_tax
                tax_rates_found.append(tax_rate_decimal)
                evidence.append(f"Line {idx + 1}: net={line_net}, tax_rate={tax_rate_decimal}, tax={line_tax}")
            else:
                evidence.append(f"Line {idx + 1}: net={line_net}, tax_rate=missing")

        total_amount = total_net + total_tax

        # Infer tax if not all items have explicit rates
        if not tax_rates_found:
            # Default inference: assume 19% VAT if no rates provided
            inferred_tax = total_net * Decimal("0.19")
            evidence.append("No tax rates provided; inferred 19% VAT on net total.")
            confidence = 0.5
        elif len(tax_rates_found) < len(line_items):
            # Partial tax info: use average of known rates
            avg_rate = sum(tax_rates_found) / len(tax_rates_found)
            inferred_tax = total_tax + (
                (
                    total_net
                    - sum(
                        Decimal(str(item.get("quantity", 0))) * Decimal(str(item.get("unit_price", 0)))
                        for item in line_items
                        if item.get("tax_rate") is not None
                    )
                )
                * avg_rate
            )
            evidence.append(f"Partial tax info; inferred average rate {avg_rate}.")
            confidence = 0.7
        else:
            # All items have tax rates
            inferred_tax = total_tax
            confidence = 1.0

        status = "valid" if len(line_items) > 0 and confidence > 0.6 else "incomplete"

        return {
            "total_amount": total_amount,
            "inferred_tax_amount": inferred_tax,
            "status": status,
            "evidence": evidence,
            "confidence": confidence,
        }

    @staticmethod
    def generate_recommendations(calculation_result: dict[str, Any], invoice: dict[str, Any]) -> list[str]:
        """
        Generate recommendations based on the invoice calculation.

        Args:
            calculation_result: The result from calculate_invoice.
            invoice: The original invoice data.

        Returns:
            A list of recommendation strings.
        """
        recommendations = []

        if calculation_result["status"] == "incomplete":
            recommendations.append("Invoice is incomplete. Verify all line items are present.")

        if calculation_result["confidence"] < 0.7:
            recommendations.append("Tax calculation confidence is low. Ensure all line items include tax_rate.")

        if calculation_result["inferred_tax_amount"] == Decimal("0.00"):
            recommendations.append("No tax detected. Confirm if this invoice is tax-exempt.")

        return recommendations
