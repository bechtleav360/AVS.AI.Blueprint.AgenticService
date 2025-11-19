"""Tests for the calculator service."""

from src.services import CalculatorService


class TestCalculatorService:
    """Test suite for CalculatorService."""

    def test_add(self) -> None:
        """Test addition operation."""
        result, error = CalculatorService.calculate(5, 3, "add")
        assert result == 8
        assert error is None

    def test_subtract(self) -> None:
        """Test subtraction operation."""
        result, error = CalculatorService.calculate(10, 4, "subtract")
        assert result == 6
        assert error is None

    def test_multiply(self) -> None:
        """Test multiplication operation."""
        result, error = CalculatorService.calculate(6, 7, "multiply")
        assert result == 42
        assert error is None

    def test_divide(self) -> None:
        """Test division operation."""
        result, error = CalculatorService.calculate(20, 4, "divide")
        assert result == 5
        assert error is None

    def test_divide_by_zero(self) -> None:
        """Test division by zero error handling."""
        result, error = CalculatorService.calculate(10, 0, "divide")
        assert result == 0
        assert error == "Division by zero"

    def test_unknown_operation(self) -> None:
        """Test unknown operation error handling."""
        result, error = CalculatorService.calculate(5, 3, "power")
        assert result == 0
        assert "Unknown operation" in error

    def test_float_operations(self) -> None:
        """Test operations with floating point numbers."""
        result, error = CalculatorService.calculate(3.5, 2.5, "add")
        assert result == 6.0
        assert error is None
