"""Text extraction handler for processing text extraction jobs.

This handler demonstrates how to use a regular EventHandler to process
jobs from the sessions service. The SessionsBus provides the sessions API
client and session key in the context.
"""

import logging
from typing import Any

from blueprint.agents.base import EventHandler
from blueprint.agents.models.events import GenericCloudEvent
from blueprint.agents.models.errors import InvalidEventError, RetryableHandlerError

logger = logging.getLogger(__name__)


class TextExtractionHandler(EventHandler):
    """Extracts text from documents in session jobs.

    This handler:
    1. Filters for "extract_text" job types via can_handle_event()
    2. Fetches full job details from sessions service (using context)
    3. Processes the job (extracts text from document)
    4. Completes the job with results (using context)

    The SessionsBus provides in context:
    - session_id: UUID of the session
    - job_id: UUID of the job
    - session_key: Session key for encrypted data access
    - sessions_api_client: SessionsApiClient instance
    - sessions_key_provider: SessionKeyProvider instance

    Example job payload:
        {
            "document_url": "https://example.com/doc.pdf",
            "document_type": "pdf",
            "options": {
                "include_metadata": true,
                "extract_tables": false
            }
        }
    """

    def __init__(self):
        super().__init__("TextExtractionHandler", priority=50)

    async def can_handle_event(
        self,
        event: GenericCloudEvent,
        context: dict[str, Any],
    ) -> bool:
        """Check if this handler can process the event.

        Args:
            event: CloudEvent to check
            context: Processing context

        Returns:
            True if this is an extract_text job, False otherwise
        """
        # Check if it's a sessions job event
        if not event.type.startswith("sessions.job.created."):
            return False

        # Check if job type is extract_text
        job_type = event.data.get("job_type")
        return job_type == "extract_text"

    async def handle_event(
        self,
        event: GenericCloudEvent,
        context: dict[str, Any],
    ) -> None:
        """Process text extraction job.

        Args:
            event: CloudEvent containing job notification
            context: Processing context with session_id, job_id, session_key

        Raises:
            InvalidEventError: If job payload is invalid
            RetryableHandlerError: If processing fails transiently
        """
        job_id = event.data.get("job_id")
        session_id = event.data.get("session_id")
        api_client = context.get("sessions_api_client")
        session_key = context.get("session_key")

        logger.info("Processing text extraction job: job_id=%s, session_id=%s", job_id, session_id)

        try:
            # Mark job as started
            await self.start_job(event, context)

            # Fetch full job details (includes encrypted payload)
            job = await self.fetch_job_details(event, context)

            # Extract payload data
            payload = job.get("payload", {})
            document_url = payload.get("document_url")
            document_type = payload.get("document_type", "unknown")
            options = payload.get("options", {})

            # Validate payload
            if not document_url:
                raise InvalidEventError("Missing document_url in job payload")

            logger.info(
                "Extracting text from document: url=%s, type=%s",
                document_url,
                document_type,
            )

            # Process the document
            # In a real implementation, you would:
            # 1. Download the document from document_url
            # 2. Extract text using appropriate library (PyPDF2, python-docx, etc.)
            # 3. Optionally use LLM agent for enhanced extraction
            #
            # For this example, we'll simulate the extraction
            extracted_text = await self._extract_text(
                document_url=document_url,
                document_type=document_type,
                options=options,
            )

            # Prepare result
            result = {
                "extracted_text": extracted_text,
                "document_type": document_type,
                "character_count": len(extracted_text),
                "metadata": {
                    "extraction_method": "simulated",
                    "options_used": options,
                },
            }

            # Complete job with results
            await api_client.complete_job(
                session_id=session_id,
                job_id=job_id,
                session_key=session_key,
                result=result,
            )

            logger.info(
                "Text extraction completed: job_id=%s, chars=%d",
                job_id,
                len(extracted_text),
            )

        except InvalidEventError:
            # Permanent failure - re-raise to auto-cancel job
            raise

        except Exception as e:
            # Unexpected error - treat as transient
            logger.error("Text extraction failed: %s", e, exc_info=True)
            raise RetryableHandlerError(f"Text extraction failed: {str(e)}") from e

    async def _extract_text(
        self,
        document_url: str,
        document_type: str,
        options: dict[str, Any],
    ) -> str:
        """Extract text from document.

        In a real implementation, this would:
        1. Download the document
        2. Use appropriate library to extract text
        3. Optionally use LLM for enhanced extraction

        Args:
            document_url: URL of the document to process
            document_type: Type of document (pdf, docx, etc.)
            options: Extraction options

        Returns:
            Extracted text content

        Raises:
            RetryableHandlerError: If extraction fails transiently
        """
        # Simulate text extraction
        # In production, replace with actual extraction logic
        logger.debug("Simulating text extraction from %s", document_url)

        # Example: Using LLM agent for extraction
        # agent = self.get_agent("text_extractor")
        # result = await agent.run(
        #     "Extract all text from this document",
        #     deps={"document_url": document_url}
        # )
        # return result.data

        # For now, return simulated text
        return f"Simulated extracted text from {document_url} (type: {document_type})"
