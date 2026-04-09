"""Pydantic models for the document summarizer service."""

from pydantic import BaseModel, Field


class DocumentRequest(BaseModel):
    """Request payload for document summarization."""

    content: str = Field(..., description="The document text to summarize")
    title: str | None = Field(default=None, description="Optional document title")


class DocumentSummary(BaseModel):
    """Structured summary produced by the LLM agent."""

    title: str = Field(..., description="Document title (generated if not provided)")
    summary: str = Field(..., description="Concise 2-3 sentence summary")
    key_points: list[str] = Field(..., description="3-5 key points from the document")
    sentiment: str = Field(
        ...,
        description="Overall sentiment: positive, negative, or neutral",
    )
    word_count: int = Field(..., description="Total word count of the document")
    reading_time_minutes: float = Field(
        ...,
        description="Estimated reading time in minutes at 200 wpm",
    )


class SummarizeResponse(BaseModel):
    """Response wrapper for a document summarization request."""

    document_id: str = Field(..., description="Unique identifier derived from content hash")
    summary: DocumentSummary = Field(..., description="The structured document summary")
