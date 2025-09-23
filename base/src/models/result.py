"""Result models for agent output and backup status."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


class BackupStatus(str, Enum):
    """Backup status enumeration."""
    
    ENABLED = "enabled"
    DISABLED = "disabled"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    ERROR = "error"


class Evidence(BaseModel):
    """Evidence supporting a backup status decision."""
    
    type: str = Field(..., description="Type of evidence (tag, uri, api_response, etc.)")
    source: str = Field(..., description="Source of the evidence")
    value: Any = Field(..., description="Evidence value or content")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    description: Optional[str] = Field(None, description="Human-readable description")
    
    @validator("confidence")
    def validate_confidence(cls, v):
        """Ensure confidence is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v


class AgentOutput(BaseModel):
    """Output from the backup checking agent."""
    
    # Core results
    asset_id: str = Field(..., description="ID of the checked asset")
    backup_status: BackupStatus = Field(..., description="Determined backup status")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence in the result")
    
    # Supporting information
    evidence: List[Evidence] = Field(default_factory=list, description="Evidence supporting the decision")
    reasoning: Optional[str] = Field(None, description="AI agent's reasoning process")
    
    # Backup details
    backup_locations: List[str] = Field(default_factory=list, description="Identified backup locations")
    backup_frequency: Optional[str] = Field(None, description="Backup frequency if detected")
    last_backup: Optional[datetime] = Field(None, description="Last backup timestamp if available")
    
    # Recommendations
    recommendations: List[str] = Field(default_factory=list, description="Recommendations for improvement")
    risk_level: Optional[str] = Field(None, description="Risk level (low, medium, high)")
    
    # Metadata
    checked_at: datetime = Field(default_factory=datetime.utcnow, description="When the check was performed")
    agent_version: Optional[str] = Field(None, description="Version of the checking agent")
    processing_time_ms: Optional[int] = Field(None, description="Processing time in milliseconds")
    
    # Correlation
    correlation_id: Optional[UUID] = Field(None, description="Correlation ID from the original request")
    event_id: Optional[UUID] = Field(None, description="ID of the event that triggered this check")
    
    @validator("confidence")
    def validate_confidence(cls, v):
        """Ensure confidence is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")
        return v
    
    @validator("evidence")
    def validate_evidence(cls, v):
        """Validate evidence list."""
        if not v:
            return v
        
        # Ensure evidence is sorted by confidence (highest first)
        sorted_evidence = sorted(v, key=lambda e: e.confidence, reverse=True)
        return sorted_evidence
    
    def get_highest_confidence_evidence(self) -> Optional[Evidence]:
        """Get the evidence with the highest confidence."""
        if not self.evidence:
            return None
        return max(self.evidence, key=lambda e: e.confidence)
    
    def get_evidence_by_type(self, evidence_type: str) -> List[Evidence]:
        """Get all evidence of a specific type."""
        return [e for e in self.evidence if e.type == evidence_type]
    
    def has_strong_evidence(self, min_confidence: float = 0.8) -> bool:
        """Check if there's strong evidence (above confidence threshold)."""
        return any(e.confidence >= min_confidence for e in self.evidence)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the backup check results."""
        return {
            "asset_id": self.asset_id,
            "backup_status": self.backup_status,
            "confidence": self.confidence,
            "evidence_count": len(self.evidence),
            "backup_locations_count": len(self.backup_locations),
            "risk_level": self.risk_level,
            "has_recommendations": len(self.recommendations) > 0,
            "checked_at": self.checked_at,
        }
    
    def to_thin_event_data(self) -> Dict[str, Any]:
        """Convert to thin event data format for publishing."""
        return {
            "asset_id": self.asset_id,
            "backup_status": self.backup_status,
            "confidence": self.confidence,
            "evidence_count": len(self.evidence),
            "backup_locations_count": len(self.backup_locations),
            "risk_level": self.risk_level,
            "checked_at": self.checked_at.isoformat(),
            "processing_time_ms": self.processing_time_ms,
        }


class CheckRequest(BaseModel):
    """Request model for backup checking."""
    
    asset_id: Optional[str] = Field(None, description="Asset ID for thin event processing")
    asset: Optional[Dict[str, Any]] = Field(None, description="Full asset data for direct checking")
    
    # Processing options
    force_recheck: bool = Field(default=False, description="Force recheck even if cached result exists")
    include_recommendations: bool = Field(default=True, description="Include recommendations in output")
    max_processing_time_s: Optional[int] = Field(None, description="Maximum processing time in seconds")
    
    # Correlation
    correlation_id: Optional[UUID] = Field(None, description="Correlation ID for tracing")
    
    @validator("asset_id", "asset")
    def validate_asset_input(cls, v, values):
        """Ensure either asset_id or asset is provided, but not both."""
        asset_id = values.get("asset_id") if "asset_id" in values else v if "asset_id" not in values else values["asset_id"]
        asset = values.get("asset") if "asset" in values else v if "asset" not in values else values["asset"]
        
        if not asset_id and not asset:
            raise ValueError("Either asset_id or asset must be provided")
        
        if asset_id and asset:
            raise ValueError("Provide either asset_id or asset, not both")
        
        return v


class CheckResponse(BaseModel):
    """Response model for backup checking."""
    
    success: bool = Field(..., description="Whether the check was successful")
    result: Optional[AgentOutput] = Field(None, description="Check result if successful")
    error: Optional[str] = Field(None, description="Error message if unsuccessful")
    error_code: Optional[str] = Field(None, description="Error code for programmatic handling")
    
    # Metadata
    request_id: Optional[str] = Field(None, description="Request identifier")
    processing_time_ms: Optional[int] = Field(None, description="Total processing time")
    
    @validator("result", "error")
    def validate_result_or_error(cls, v, values):
        """Ensure result is provided on success, error on failure."""
        success = values.get("success", False)
        
        if success and not v and "result" in cls.__fields__:
            raise ValueError("Result must be provided when success is True")
        
        if not success and not v and "error" in cls.__fields__:
            raise ValueError("Error must be provided when success is False")
        
        return v
