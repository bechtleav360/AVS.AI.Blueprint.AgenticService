"""Domain models: what SummarizerService works with. No request DTO reaches the service."""

from pydantic import BaseModel, Field


class Document(BaseModel):
    """A document to summarize."""

    content: str
    title: str | None = None


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


class SummaryRecord(BaseModel):
    """A summary and the content-derived id it is stored under."""

    document_id: str
    summary: DocumentSummary
