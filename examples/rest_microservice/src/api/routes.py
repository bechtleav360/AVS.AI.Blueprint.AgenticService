"""REST API for the microservice."""

import logging

from blueprint.agents.base import RestApi

from ..models import CalculationRequest, CalculationResult

logger = logging.getLogger(__name__)


class CalculatorRestApi(RestApi):
    """REST API for calculator operations."""

    def __init__(self) -> None:
        """Initialize the calculator REST API.

        The component registry will be wired in by AppBuilder.
        """
        super().__init__(name="CalculatorRestApi")

    async def on_startup(self) -> None:
        """Initialize the REST API by getting the calculator service from the registry."""
        self._calculator_service = self.get_registry().get_service("calculator_service")

    @RestApi.get("/calculate", response_model=CalculationResult)
    async def calculate(self, a: float, b: float, operation: str) -> CalculationResult:
        """Perform a calculation.

        Args:
            a: First operand
            b: Second operand
            operation: Operation ('add', 'subtract', 'multiply', 'divide')

        Returns:
            CalculationResult with the result or error
        """
        result, error = self._calculator_service.calculate(a, b, operation)

        return CalculationResult(
            a=a,
            b=b,
            operation=operation,
            result=result if error is None else 0,
            error=error,
        )

    @RestApi.post("/calculate", response_model=CalculationResult)
    async def calculate_post(self, request: CalculationRequest) -> CalculationResult:
        """Perform a calculation using POST.

        Args:
            request: CalculationRequest with operands and operation

        Returns:
            CalculationResult with the result or error
        """
        result, error = self._calculator_service.calculate(request.a, request.b, request.operation)

        return CalculationResult(
            a=request.a,
            b=request.b,
            operation=request.operation,
            result=result if error is None else 0,
            error=error,
        )
