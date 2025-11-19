"""Request and response schemas for the REST microservice."""

from pydantic import BaseModel, Field


class CalculationRequest(BaseModel):
    """Request model for calculations."""

    a: float = Field(..., description="First operand")
    b: float = Field(..., description="Second operand")
    operation: str = Field(..., description="Operation: 'add', 'subtract', 'multiply', 'divide'")


class CalculationResult(BaseModel):
    """Response model for calculation results."""

    a: float = Field(..., description="First operand")
    b: float = Field(..., description="Second operand")
    operation: str = Field(..., description="Operation performed")
    result: float = Field(..., description="Calculation result")
    error: str | None = Field(None, description="Error message if calculation failed")
