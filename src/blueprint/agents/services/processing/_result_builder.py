"""Result builder for processing outcomes."""

from typing import Any

from ...models import ProcessingResult, ProcessingStatus
from ...models.events import HandlerResult


class _ResultBuilder:
    """Builds processing result data structures."""

    @staticmethod
    def extract_handler_result(handler_result: Any) -> list[HandlerResult]:
        """
        Normalize handler outputs to a list of HandlerResult objects.

        Args:
            handler_result: Result from handler execution (single result, list of results, or other)

        Returns:
            List of HandlerResult objects
        """

        def _to_handler_result(value: Any) -> HandlerResult:
            if isinstance(value, HandlerResult):
                return value

            if isinstance(value, dict):
                event_type = value.get("event_type") or None
                raw_metadata = value.get("metadata")
                metadata = raw_metadata if isinstance(raw_metadata, dict) else {}

                data = value.get("data")
                if not isinstance(data, dict):
                    if event_type is None and not metadata:
                        # Arbitrary dict payload without special keys – treat entire dict as data
                        data = value
                    else:
                        data = {"value": data}

                return HandlerResult(
                    event_type=event_type,
                    data=data,
                    metadata=metadata,
                )

            return HandlerResult(event_type=None, data=value, metadata={})

        if handler_result is None:
            return []

        # Handler returned a list of results
        if isinstance(handler_result, list):
            return [_to_handler_result(item) for item in handler_result]

        # Single result (HandlerResult, dict, or other)
        return [_to_handler_result(handler_result)]

    @staticmethod
    def build_result_data(
        request_id: str,
        handler_results: list[HandlerResult],
        status: ProcessingStatus,
    ) -> ProcessingResult:
        """
        Build result data dictionary.

        Args:
            request_id: Request identifier
            handler_results: List of handler results
            status: Processing status indicator

        Returns:
            ProcessingResult model
        """
        message = "Message acknowledged"
        if status == ProcessingStatus.NO_HANDLER_FOUND:
            message = "No handler processed this event"

        return ProcessingResult(
            request_id=request_id,
            status=status,
            result=handler_results,
            metadata={},
            message=message,
        )
