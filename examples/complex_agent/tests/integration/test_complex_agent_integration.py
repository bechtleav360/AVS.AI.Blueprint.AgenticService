"""Integration tests for the Complex Agent example.

Tests the complete workflow of the complex agent including:
- Invoice processing
- Handler invocation
- Event processing
- Agent analysis
"""

import pytest
from blueprint.agents.models.events import CloudEvent

from examples.complex_agent.src.handlers import (
    AgentInvokerHandler,
    SimpleProcessorHandler,
)
from examples.complex_agent.src.models import CustomPayload
from examples.complex_agent.src.models.resource import InvoiceInput, InvoiceLineItem
from examples.complex_agent.src.services import (
    HealthCheckService,
    InvoiceProcessingLogic,
)


class TestComplexAgentIntegration:
    """Integration tests for the complex agent workflow."""

    @pytest.fixture
    def sample_invoice_text(self) -> str:
        """Provide sample invoice text."""
        return """
        Invoice #INV-2025-001
        Date: 2025-01-15
        Customer: Bechtle AG

        Line Items:
        1. Consulting services - Qty: 10 hrs @ 150.00 EUR/hr = 1500.00 EUR
        2. Software license - Qty: 1 @ 500.00 EUR = 500.00 EUR

        Subtotal: 2000.00 EUR
        Tax (19%): 380.00 EUR
        Total: 2380.00 EUR
        """

    @pytest.fixture
    def sample_payload(self, sample_invoice_text: str) -> CustomPayload:
        """Create a sample payload."""
        return CustomPayload(
            invoice_text=sample_invoice_text,
            details={"action": "invoke_agent", "source": "ocr_scanner"},
        )

    @pytest.fixture
    def sample_cloud_event(self, sample_payload: CustomPayload) -> CloudEvent:
        """Create a sample cloud event."""
        return CloudEvent(
            id="test-123",
            type="invoice.received",
            source="/invoice-processor",
            data=sample_payload,
        )

    def test_agent_invoker_handler_initialization(self):
        """Test AgentInvokerHandler can be initialized."""
        handler = AgentInvokerHandler()
        assert handler is not None
        assert isinstance(handler, AgentInvokerHandler)

    def test_simple_processor_handler_initialization(self):
        """Test SimpleProcessorHandler can be initialized."""
        handler = SimpleProcessorHandler()
        assert handler is not None
        assert isinstance(handler, SimpleProcessorHandler)

    @pytest.mark.asyncio
    async def test_agent_invoker_can_handle_invoke_action(self, sample_cloud_event):
        """Test AgentInvokerHandler recognizes invoke_agent action."""
        handler = AgentInvokerHandler()
        can_handle = await handler.can_handle_event(sample_cloud_event, {})
        assert can_handle is True

    @pytest.mark.asyncio
    async def test_agent_invoker_cannot_handle_other_actions(self):
        """Test AgentInvokerHandler rejects non-invoke_agent actions."""
        handler = AgentInvokerHandler()
        payload = CustomPayload(
            invoice_text="Test invoice",
            details={"action": "other_action"},
        )
        event = CloudEvent(
            id="test-456",
            type="invoice.received",
            source="/invoice-processor",
            data=payload,
        )
        can_handle = await handler.can_handle_event(event, {})
        assert can_handle is False

    @pytest.mark.asyncio
    async def test_simple_processor_can_handle_custom_payload(self):
        """Test SimpleProcessorHandler can handle custom payloads."""
        handler = SimpleProcessorHandler()
        payload = CustomPayload(
            invoice_text="Test invoice",
            details={"action": "simple_process", "invoice_id": "inv-1"},
        )
        event = CloudEvent(
            id="test-789",
            type="invoice.received",
            source="/invoice-processor",
            data=payload,
        )
        can_handle = await handler.can_handle_event(event, {})
        assert can_handle is True

    @pytest.mark.asyncio
    async def test_simple_processor_rejects_non_custom_payload(self):
        """Test SimpleProcessorHandler rejects non-custom payloads."""
        handler = SimpleProcessorHandler()
        event = CloudEvent(
            id="test-000",
            type="invoice.received",
            source="/invoice-processor",
            data={"details": {"action": "simple_process"}},
        )
        can_handle = await handler.can_handle_event(event, {})
        assert can_handle is False


class TestInvoiceProcessingLogic:
    """Integration tests for invoice processing logic."""

    @pytest.fixture
    def sample_invoice_dict(self) -> dict:
        """Provide sample invoice dictionary."""
        return {
            "invoice_id": "INV-100",
            "line_items": [
                {
                    "description": "Consulting",
                    "quantity": "10",
                    "unit_price": "150",
                    "tax_rate": "0.19",
                },
                {
                    "description": "Software",
                    "quantity": "1",
                    "unit_price": "500",
                    "tax_rate": "0.07",
                },
            ],
            "currency": "EUR",
        }

    def test_invoice_calculation_returns_valid_result(self, sample_invoice_dict):
        """Test invoice calculation returns valid result."""
        result = InvoiceProcessingLogic.calculate_invoice(sample_invoice_dict)

        assert result is not None
        assert "status" in result
        assert "total_amount" in result
        assert "evidence" in result
        assert "confidence" in result

    def test_invoice_calculation_with_valid_items(self, sample_invoice_dict):
        """Test invoice calculation with valid line items."""
        result = InvoiceProcessingLogic.calculate_invoice(sample_invoice_dict)

        assert result["status"] == "valid"
        assert float(result["total_amount"]) > 0
        assert result["confidence"] >= 0.7

    def test_invoice_calculation_with_empty_items(self):
        """Test invoice calculation with empty line items."""
        invoice = {"line_items": []}
        result = InvoiceProcessingLogic.calculate_invoice(invoice)

        assert result["status"] == "incomplete"
        assert float(result["total_amount"]) == 0.0

    def test_invoice_calculation_with_missing_items(self):
        """Test invoice calculation with missing line items."""
        invoice = {}
        result = InvoiceProcessingLogic.calculate_invoice(invoice)

        assert result["status"] == "incomplete"

    def test_generate_recommendations_returns_list(self, sample_invoice_dict):
        """Test generate_recommendations returns a list."""
        calculation = InvoiceProcessingLogic.calculate_invoice(sample_invoice_dict)
        recommendations = InvoiceProcessingLogic.generate_recommendations(calculation, sample_invoice_dict)

        assert isinstance(recommendations, list)

    def test_generate_recommendations_for_valid_invoice(self, sample_invoice_dict):
        """Test generate_recommendations for valid invoice."""
        calculation = InvoiceProcessingLogic.calculate_invoice(sample_invoice_dict)
        recommendations = InvoiceProcessingLogic.generate_recommendations(calculation, sample_invoice_dict)

        assert isinstance(recommendations, list)

    def test_generate_recommendations_for_incomplete_invoice(self):
        """Test generate_recommendations for incomplete invoice."""
        invoice = {"line_items": []}
        calculation = InvoiceProcessingLogic.calculate_invoice(invoice)
        recommendations = InvoiceProcessingLogic.generate_recommendations(calculation, invoice)

        assert isinstance(recommendations, list)


class TestHealthCheckService:
    """Integration tests for health check service."""

    @pytest.mark.asyncio
    async def test_health_check_service_returns_true(self):
        """Test health check service returns True."""
        service = HealthCheckService()
        result = await service.check_health()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_service_is_responsive(self):
        """Test health check service is responsive."""
        service = HealthCheckService()
        # Multiple calls should all return True
        for _ in range(3):
            result = await service.check_health()
            assert result is True


class TestInvoiceInputModel:
    """Integration tests for InvoiceInput model."""

    def test_invoice_input_creation(self):
        """Test InvoiceInput can be created."""
        line_item = InvoiceLineItem(
            description="Test item",
            quantity=1,
            unit_price=100.0,
            tax_rate=0.19,
        )
        invoice = InvoiceInput(
            invoice_id="INV-001",
            line_items=[line_item],
            currency="EUR",
        )

        assert invoice.invoice_id == "INV-001"
        assert len(invoice.line_items) == 1
        assert invoice.currency == "EUR"

    def test_invoice_line_item_creation(self):
        """Test InvoiceLineItem can be created."""
        from decimal import Decimal

        line_item = InvoiceLineItem(
            description="Consulting services",
            quantity=10,
            unit_price=150.0,
            tax_rate=0.19,
        )

        assert line_item.description == "Consulting services"
        assert line_item.quantity == Decimal("10")
        assert line_item.unit_price == Decimal("150.0")
        assert line_item.tax_rate == Decimal("0.19")

    def test_invoice_input_with_multiple_items(self):
        """Test InvoiceInput with multiple line items."""
        items = [
            InvoiceLineItem(
                description="Item 1",
                quantity=5,
                unit_price=100.0,
                tax_rate=0.19,
            ),
            InvoiceLineItem(
                description="Item 2",
                quantity=3,
                unit_price=200.0,
                tax_rate=0.07,
            ),
        ]
        invoice = InvoiceInput(
            invoice_id="INV-002",
            line_items=items,
            currency="EUR",
        )

        assert len(invoice.line_items) == 2
        assert invoice.line_items[0].description == "Item 1"
        assert invoice.line_items[1].description == "Item 2"


class TestComplexAgentScenarios:
    """Integration tests for complex agent scenarios."""

    @pytest.fixture
    def consulting_invoice(self) -> dict:
        """Provide a consulting services invoice."""
        return {
            "invoice_id": "INV-CONSULT-001",
            "line_items": [
                {
                    "description": "Consulting services",
                    "quantity": "40",
                    "unit_price": "200",
                    "tax_rate": "0.19",
                },
            ],
            "currency": "EUR",
        }

    @pytest.fixture
    def mixed_invoice(self) -> dict:
        """Provide a mixed services and products invoice."""
        return {
            "invoice_id": "INV-MIXED-001",
            "line_items": [
                {
                    "description": "Consulting",
                    "quantity": "20",
                    "unit_price": "150",
                    "tax_rate": "0.19",
                },
                {
                    "description": "Software license",
                    "quantity": "5",
                    "unit_price": "500",
                    "tax_rate": "0.07",
                },
                {
                    "description": "Support services",
                    "quantity": "12",
                    "unit_price": "100",
                    "tax_rate": "0.19",
                },
            ],
            "currency": "EUR",
        }

    def test_consulting_invoice_processing(self, consulting_invoice):
        """Test processing a consulting services invoice."""
        result = InvoiceProcessingLogic.calculate_invoice(consulting_invoice)

        assert result["status"] == "valid"
        assert float(result["total_amount"]) > 0
        assert result["confidence"] >= 0.7

    def test_mixed_invoice_processing(self, mixed_invoice):
        """Test processing a mixed services and products invoice."""
        result = InvoiceProcessingLogic.calculate_invoice(mixed_invoice)

        assert result["status"] == "valid"
        assert float(result["total_amount"]) > 0
        assert result["confidence"] >= 0.7

    def test_invoice_with_high_value_items(self):
        """Test processing invoice with high-value items."""
        invoice = {
            "invoice_id": "INV-HIGH-001",
            "line_items": [
                {
                    "description": "Enterprise software",
                    "quantity": "1",
                    "unit_price": "50000",
                    "tax_rate": "0.19",
                },
            ],
            "currency": "EUR",
        }
        result = InvoiceProcessingLogic.calculate_invoice(invoice)

        assert result["status"] == "valid"
        assert float(result["total_amount"]) > 50000

    def test_invoice_with_multiple_tax_rates(self):
        """Test processing invoice with multiple tax rates."""
        invoice = {
            "invoice_id": "INV-MULTI-TAX-001",
            "line_items": [
                {
                    "description": "Item 19%",
                    "quantity": "10",
                    "unit_price": "100",
                    "tax_rate": "0.19",
                },
                {
                    "description": "Item 7%",
                    "quantity": "5",
                    "unit_price": "200",
                    "tax_rate": "0.07",
                },
                {
                    "description": "Item 0%",
                    "quantity": "2",
                    "unit_price": "500",
                    "tax_rate": "0.0",
                },
            ],
            "currency": "EUR",
        }
        result = InvoiceProcessingLogic.calculate_invoice(invoice)

        assert result["status"] == "valid"
        assert float(result["total_amount"]) > 0

    def test_complete_invoice_workflow(self, consulting_invoice):
        """Test complete invoice processing workflow."""
        # 1. Calculate invoice
        calculation = InvoiceProcessingLogic.calculate_invoice(consulting_invoice)
        assert calculation["status"] == "valid"

        # 2. Generate recommendations
        recommendations = InvoiceProcessingLogic.generate_recommendations(calculation, consulting_invoice)
        assert isinstance(recommendations, list)

        # 3. Verify recommendations are strings (if any)
        assert all(isinstance(rec, str) for rec in recommendations)

    def test_multiple_invoice_processing_workflow(self):
        """Test processing multiple invoices."""
        invoices = [
            {
                "invoice_id": "INV-001",
                "line_items": [
                    {
                        "description": "Service 1",
                        "quantity": "10",
                        "unit_price": "100",
                        "tax_rate": "0.19",
                    }
                ],
                "currency": "EUR",
            },
            {
                "invoice_id": "INV-002",
                "line_items": [
                    {
                        "description": "Service 2",
                        "quantity": "5",
                        "unit_price": "200",
                        "tax_rate": "0.07",
                    }
                ],
                "currency": "EUR",
            },
        ]

        results = []
        for invoice in invoices:
            result = InvoiceProcessingLogic.calculate_invoice(invoice)
            results.append(result)

        assert len(results) == 2
        assert all(r["status"] == "valid" for r in results)

    @pytest.mark.asyncio
    async def test_handler_event_processing_workflow(self):
        """Test complete handler event processing workflow."""
        # 1. Create payload
        payload = CustomPayload(
            invoice_text="Invoice #INV-001\nTotal: 1000 EUR",
            details={"action": "invoke_agent"},
        )

        # 2. Create event
        event = CloudEvent(
            id="evt-001",
            type="invoice.received",
            source="/processor",
            data=payload,
        )

        # 3. Test handler can handle
        handler = AgentInvokerHandler()
        can_handle = await handler.can_handle_event(event, {})
        assert can_handle is True

    def test_invoice_calculation_consistency(self):
        """Test invoice calculation is consistent."""
        invoice = {
            "invoice_id": "INV-CONSISTENCY",
            "line_items": [
                {
                    "description": "Item",
                    "quantity": "10",
                    "unit_price": "100",
                    "tax_rate": "0.19",
                }
            ],
            "currency": "EUR",
        }

        # Calculate multiple times
        results = [InvoiceProcessingLogic.calculate_invoice(invoice) for _ in range(3)]

        # All results should be identical
        assert all(r["status"] == results[0]["status"] for r in results)
        assert all(r["total_amount"] == results[0]["total_amount"] for r in results)
