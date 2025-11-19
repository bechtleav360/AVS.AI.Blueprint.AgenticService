"""REST API for the microservice."""

import logging
from typing import Any

from blueprint.agents.api.rest import RestApi

from ..models import CalculationRequest, CalculationResult
from ..services import CalculatorService

logger = logging.getLogger(__name__)


class CalculatorRestApi(RestApi):
    """REST API for calculator operations."""

    def __init__(self) -> None:
        """Initialize the calculator REST API.

        The component registry will be wired in by AppBuilder.
        """
        # Initialize with a placeholder registry - will be wired by AppBuilder
        self._component_registry: Any = None
        self.calculator_service = CalculatorService
        # Don't call super().__init__() yet - wait for registry to be wired
        self.router = None
        self.payload_type = CalculationRequest

    def _register_routes(self) -> None:
        """Register calculator-specific routes."""

        @self.router.get("/calculate", response_model=CalculationResult)
        async def calculate(a: float, b: float, operation: str) -> CalculationResult:
            """Perform a calculation.

            Args:
                a: First operand
                b: Second operand
                operation: Operation ('add', 'subtract', 'multiply', 'divide')

            Returns:
                CalculationResult with the result or error
            """
            result, error = self.calculator_service.calculate(a, b, operation)

            return CalculationResult(
                a=a,
                b=b,
                operation=operation,
                result=result if error is None else 0,
                error=error,
            )

        @self.router.post("/calculate", response_model=CalculationResult)
        async def calculate_post(request: CalculationRequest) -> CalculationResult:
            """Perform a calculation using POST.

            Args:
                request: CalculationRequest with operands and operation

            Returns:
                CalculationResult with the result or error
            """
            result, error = self.calculator_service.calculate(request.a, request.b, request.operation)

            return CalculationResult(
                a=request.a,
                b=request.b,
                operation=request.operation,
                result=result if error is None else 0,
                error=error,
            )
