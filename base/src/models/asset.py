"""Generic resource/context models for agent processing."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class ResourceType(str, Enum):
    """
    Generic resource types for agent processing.

    FIXME: Replace with your domain-specific resource types
    FIXME: Add types relevant to your business domain
    """
    UNKNOWN = "unknown"
    # FIXME: Add your custom resource types here
    # RESOURCE_TYPE_1 = "resource_type_1"
    # RESOURCE_TYPE_2 = "resource_type_2"
    # RESOURCE_TYPE_3 = "resource_type_3"


class DeploymentType(str, Enum):
    """
    Generic deployment types.

    FIXME: Replace with your deployment/infrastructure types
    FIXME: Add types relevant to your infrastructure
    """
    UNKNOWN = "unknown"
    # FIXME: Add your custom deployment types here
    # CLOUD = "cloud"
    # ON_PREMISE = "on_premise"
    # HYBRID = "hybrid"


class ResourceMetadata(BaseModel):
    """
    Generic resource metadata for agent processing.

    FIXME: Customize fields for your domain-specific requirements
    FIXME: Add validation, computed properties, and business logic
    """

    id: str = Field(..., description="Unique resource identifier")
    name: str = Field(..., description="Human-readable resource name")
    type: ResourceType = Field(..., description="Type of the resource")
    deployment: DeploymentType = Field(..., description="Deployment type")

    # FIXME: Add your domain-specific fields here
    # Location and networking
    region: Optional[str] = Field(None, description="Geographic region or data center")
    zone: Optional[str] = Field(None, description="Availability zone")
    network_id: Optional[str] = Field(None, description="Network identifier")

    # Resource-specific identifiers
    resource_id: Optional[str] = Field(None, description="Provider-specific resource ID")
    resource_ref: Optional[str] = Field(None, description="Reference identifier")

    # Metadata
    tags: Dict[str, str] = Field(default_factory=dict, description="Resource tags and labels")
    uris: List[str] = Field(default_factory=list, description="Related resource URIs")

    # Operational metadata
    created_at: Optional[datetime] = Field(None, description="Resource creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    status: str = Field(default="active", description="Resource operational status")

    # Ownership and organization
    environment: Optional[str] = Field(None, description="Environment (prod, staging, dev)")
    owner: Optional[str] = Field(None, description="Resource owner or team")
    organization: Optional[str] = Field(None, description="Organization or business unit")

    # Extensibility
    properties: Dict[str, Any] = Field(default_factory=dict, description="Additional resource properties")

    @validator("uris")
    def validate_uris(cls, v):
        """
        Validate URI format.

        FIXME: Enhance with your domain-specific URI validation
        FIXME: Add support for your resource-specific URI patterns
        """
        if not v:
            return v

        for uri in v:
            if not isinstance(uri, str) or len(uri.strip()) == 0:
                raise ValueError(f"Invalid URI: {uri}")

        return v

    @validator("tags")
    def validate_tags(cls, v):
        """
        Validate tags format and content.

        FIXME: Customize sensitive data validation for your domain
        FIXME: Add your organization-specific tag validation rules
        """
        if not v:
            return v

        # FIXME: Customize sensitive keys for your domain
        sensitive_keys = {"password", "secret", "key", "token", "credential"}
        for key in v.keys():
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                raise ValueError(f"Sensitive data not allowed in tags: {key}")

        return v

    # FIXME: Add your domain-specific methods here
    # def is_relevant_for_processing(self) -> bool:
    #     """Check if resource is relevant for your agent processing."""
    #     # Your custom logic here
    #     return True
    #
    # def get_domain_context(self) -> Dict[str, Any]:
    #     """Extract domain-specific context information."""
    #     # Your custom logic here
    #     return {}
    #
    # def validate_business_rules(self) -> List[str]:
    #     """Validate against your business rules."""
    #     # Your custom validation logic here
    #     return []


class ProcessingContext(BaseModel):
    """
    Context information for agent processing.

    FIXME: Customize with your domain-specific context data
    FIXME: Add fields relevant to your processing requirements
    """

    # FIXME: Add your context fields here
    correlation_id: Optional[str] = Field(None, description="Processing correlation ID")
    request_id: Optional[str] = Field(None, description="Original request ID")
    tenant_id: Optional[str] = Field(None, description="Tenant or organization ID")
    user_id: Optional[str] = Field(None, description="User ID if applicable")

    # Processing metadata
    source: Optional[str] = Field(None, description="Event source")
    channel: Optional[str] = Field(None, description="Processing channel")
    priority: int = Field(default=5, description="Processing priority (1-10)")

    # Additional context data
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context data")

    # FIXME: Add your domain-specific context fields
    # business_unit: Optional[str] = None
    # cost_center: Optional[str] = None
    # compliance_level: Optional[str] = None
    # processing_deadline: Optional[datetime] = None
