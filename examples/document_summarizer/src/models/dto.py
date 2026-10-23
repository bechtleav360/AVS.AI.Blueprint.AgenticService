"""DTOs: the REST API's wire contract."""

from pydantic import BaseModel, Field

from .domain_models import DocumentSummary


class DocumentRequest(BaseModel):
    """Request payload for document summarization."""

    content: str = Field(..., description="The document text to summarize")
    title: str | None = Field(default=None, description="Optional document title")


class SummarizeResponse(BaseModel):
    """Response payload for a summary."""

    document_id: str = Field(..., description="Unique identifier derived from content hash")
    summary: DocumentSummary = Field(..., description="The structured document summary")
