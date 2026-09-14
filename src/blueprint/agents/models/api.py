"""API-related data models for the agent service."""

from typing import Any

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


class CloudEventDataPayload(BaseModel):
    """Represents the `data` section of a CloudEvent.

    This is a generic base model with common fields. Custom implementations
    should extend or replace this model with domain-specific fields.
    """

    tenant_id: str | None = Field(
        default=None,
        alias="tenantId",
        description="Tenant identifier (example field - customize as needed)",
        examples=["tenant-42"],
    )
    asset_id: str | None = Field(
        default=None,
        alias="assetId",
        description="Asset identifier (example field - customize as needed)",
        examples=["asset-12345"],
    )
    resource_type: str | None = Field(
        default=None,
        alias="resourceType",
        description="Resource type (example field - customize as needed)",
        examples=["database"],
    )
    correlation_id: str | None = Field(
        default=None,
        alias="correlationId",
        description="Correlation identifier propagated across services.",
        examples=["7aa7f7b8-5ed9-4f43-bab3-d4a6e67f2fd5"],
    )
    result: str | None = Field(
        default=None,
        description="Outcome reported by the event (if applicable).",
        examples=["success"],
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific details forwarded from the event.",
        examples=[{"snapshot_id": "snap-01", "duration_ms": 5230}],
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional attributes included in the CloudEvent data.",
        examples=[{"region": "westeurope", "backup_enabled": True}],
    )
    model_config = ConfigDict(
        extra="allow",
        validate_by_name=True,
        json_schema_extra={
            "example": {
                "tenantId": "tenant-42",
                "assetId": "asset-12345",
                "resourceType": "database",
                "correlationId": ("7aa7f7b8-5ed9-4f43-bab3-d4a6e67f2fd5"),
                "result": "success",
                "details": {
                    "snapshot_id": "snap-01",
                    "duration_ms": 5230,
                },
                "attributes": {
                    "region": "westeurope",
                    "backup_enabled": True,
                },
            }
        },
    )


class CloudEventResponse(BaseModel):
    """Response returned after generic CloudEvent processing."""

    status: str = Field(..., examples=["processed"])
    message: str = Field(..., examples=["Event processed successfully"])


class ProcessResourceRequest(BaseModel):
    """Standard request model for resource processing endpoints.

    This is a base model that can be extended for domain-specific use cases.
    Agents can either use this model directly or create custom models that
    extend it with additional fields.
    """

    resource_id: str = Field(
        ...,
        description="Unique identifier for the resource to process",
        examples=["res-12345", "invoice-789", "asset-456"],
    )
    tenant_id: str | None = Field(
        None,
        description="Tenant identifier for multi-tenant scenarios",
        examples=["tenant-42"],
    )
    operation: str | None = Field(
        None,
        description="Operation to perform on the resource",
        examples=["analyze", "validate", "transform", "process"],
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters for the operation",
        examples=[{"include_details": True, "language": "en"}],
    )

    model_config = ConfigDict(
        extra="allow",  # Allow additional fields for extensibility
        json_schema_extra={
            "example": {
                "resource_id": "invoice-789",
                "tenant_id": "tenant-42",
                "operation": "analyze",
                "parameters": {
                    "include_details": True,
                    "language": "en",
                },
            }
        },
    )


class ProcessResourceResponse(BaseModel):
    """Illustrative response for resource processing."""

    success: bool = Field(True, examples=[True])
    request_id: str = Field(
        ...,
        examples=["9f2c1f2e-09d8-4d0d-9b6f-2f6fef2ad87a"],
    )
    message: str = Field(
        ...,
        examples=["Processing completed successfully"],
    )
    data: Any | None = Field(
        None,
        description="Processing results from handlers or agent",
    )


# --- Health Check Models ---


class LivenessResponse(BaseModel):
    """Response for the liveness probe."""

    status: str = Field(..., description="Indicates the service is running.", examples=["UP"])


class ComponentHealth(BaseModel):
    """Health status of a single downstream component."""

    status: str = Field(
        ...,
        description="Health status of the component.",
        examples=["healthy", "unhealthy"],
    )
    message: str | None = Field(
        default=None,
        description="An optional message providing more details on the component's status.",
        examples=["Connection successful."],
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="Optional diagnostic detail payload.",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "message": "Connection to database successful.",
            }
        }
    )


class NamespaceReadiness(BaseModel):
    """One agent's contribution to the readiness verdict.

    Present because ``readiness_policy`` makes the overall status no longer derivable from
    ``components``: a pod can answer ``UP`` with a failing check on it, because the agent that
    check belongs to was not flagged critical. Without this section an operator would see a
    contradiction and no way to resolve it.
    """

    status: str = Field(
        ...,
        description="Whether every one of this agent's health checks passed.",
        examples=["UP", "DOWN"],
    )
    critical: bool = Field(
        ...,
        description="Whether this agent gates readiness under the 'critical' policy.",
    )
    failing: list[str] = Field(
        default_factory=list,
        description="The entry keys of this agent's checks that are not healthy.",
    )


class ReadinessResponse(BaseModel):
    """Response for the readiness probe, including downstream components."""

    status: str = Field(
        ...,
        description="Overall health status of the service.",
        examples=["UP", "DOWN"],
    )
    components: dict[str, ComponentHealth] = Field(
        ...,
        description="Health status of individual components.",
    )
    policy: str = Field(
        default="all",
        description="The readiness policy in force, which decides how a degraded agent affects the overall status.",
        examples=["all", "critical", "any"],
    )
    namespaces: dict[str, NamespaceReadiness] = Field(
        default_factory=dict,
        description="Per-agent health, keyed by agent name ('<root>' for the root namespace).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "UP",
                "components": {
                    "database": {
                        "status": "healthy",
                        "message": "Connection successful.",
                    },
                    "redis": {
                        "status": "unhealthy",
                        "message": "Failed to connect to endpoint.",
                    },
                },
                "policy": "critical",
                "namespaces": {
                    "<root>": {"status": "UP", "critical": True, "failing": []},
                    "orders": {"status": "DOWN", "critical": False, "failing": ["orders.cache"]},
                },
            }
        }
    )


class AIModelHealth(BaseModel):
    """Health status of the AI model."""

    status: str = Field(
        ...,
        description="Health status of the AI model.",
        examples=["healthy", "unhealthy"],
    )
    model: str = Field(
        ...,
        description="The AI model identifier.",
        examples=["openai:gpt-4", "vllm:qwen2.5-7b-instruct"],
    )
    response_time_ms: int = Field(
        ...,
        description="Response time in milliseconds for the health check.",
        examples=[250],
    )


class CustomCheckHealth(BaseModel):
    """Health status of custom domain-specific checks."""

    status: str = Field(
        ...,
        description="Health status of the custom check.",
        examples=["healthy", "unhealthy"],
    )


class CacheStatsResponse(BaseModel):
    """What one cache reports about itself. **The fields are the backend's, not this model's.**

    A disk cache and a Redis cache have almost nothing to report in common: the disk backend
    answers with its directory, its entry count and its eviction policy, while Redis answers
    with a server version, a client count and its key prefix. So every field here is optional
    and extras are kept -- the payload is whatever ``CacheService.get_stats`` returned, and the
    route drops the fields the backend in use did not fill in.

    It was not always so: the four disk fields were required and a fifth, ``ttl_tracked_keys``,
    was required and produced by **no** backend, so ``GET /cache/stats`` raised a
    ``ValidationError`` and answered 500 -- on Redis it was missing all five. The endpoint's only
    test passed a hand-written dictionary through a ``MagicMock``, inventing the field that does
    not exist; a real cache was never asked. That is the failure *probe against real objects*
    names, and the test now constructs a `DiskCacheService`.
    """

    model_config = ConfigDict(extra="allow")

    size: int | None = Field(default=None, description="Entries held, for a backend that counts them")
    cache_dir: str | None = Field(default=None, description="Directory the disk backend writes to")
    size_limit: int | None = Field(default=None, description="Configured maximum size in bytes, for the disk backend")
    eviction_policy: str | None = Field(default=None, description="Eviction policy in force, for the disk backend")


class CacheNamespacesResponse(BaseModel):
    """List of cache namespaces response model."""

    namespaces: list[str]
    count: int


class CacheEvictRequest(BaseModel):
    """Request to evict (clear) cache contents."""

    namespace: str | None = None


class AgentHealthDependencies(BaseModel):
    """Dependencies checked during agent health check."""

    ai_model: AIModelHealth = Field(
        ...,
        description="Health status of the AI model.",
    )
    custom_check: CustomCheckHealth = Field(
        ...,
        description="Health status of custom domain-specific checks.",
    )


class AgentHealthResponse(BaseModel):
    """Response for agent health check."""

    status: str = Field(
        ...,
        description="Overall health status of the agent.",
        examples=["healthy", "unhealthy"],
    )
    dependencies: AgentHealthDependencies = Field(
        ...,
        description="Health status of agent dependencies.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "dependencies": {
                    "ai_model": {
                        "status": "healthy",
                        "model": "openai:gpt-4",
                        "response_time_ms": 250,
                    },
                    "custom_check": {
                        "status": "healthy",
                    },
                },
            }
        }
    )
