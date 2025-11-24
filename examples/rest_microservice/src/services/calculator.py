"""Calculator service for performing mathematical operations."""

import logging

from blueprint.agents.base.business_service import BusinessService

logger = logging.getLogger(__name__)


class CalculatorService(BusinessService):
    """Service for performing calculations."""

    def __init__(self) -> None:
        """Initialize the calculator service."""
        super().__init__("calculator_service")

    def calculate(self, a: float, b: float, operation: str) -> tuple[float, str | None]:
        """Perform a calculation.

        Args:
            a: First operand
            b: Second operand
            operation: Operation to perform ('add', 'subtract', 'multiply', 'divide')

        Returns:
            Tuple of (result, error_message)
            - result: The calculation result (or 0 if error)
            - error_message: Error message if operation failed, None if successful
        """
        try:
            if operation == "add":
                result = a + b
            elif operation == "subtract":
                result = a - b
            elif operation == "multiply":
                result = a * b
            elif operation == "divide":
                if b == 0:
                    return 0, "Division by zero"
                result = a / b
            else:
                return 0, f"Unknown operation: {operation}"

            logger.info(f"Calculation successful: {a} {operation} {b} = {result}")
            return result, None

        except Exception as e:
            error_msg = f"Calculation error: {str(e)}"
            logger.error(error_msg)
            return 0, error_msg
