"""Result builder for processing outcomes."""

from typing import Any


class _ResultBuilder:
    """Builds processing result data structures."""

    @staticmethod
    def extract_handler_result(
        handler_result: Any,
    ) -> tuple[str | None, Any | None, dict[str, Any]] | tuple[list[tuple[str | None, Any | None, dict[str, Any]]], None, None]:
        """
        Extract event_type, data, and metadata from handler result.

        Supports both single HandlerResult and list of HandlerResults.

        Args:
            handler_result: Result from handler execution (single result, list of results, or other)

        Returns:
            For single result: Tuple of (event_type, data, metadata)
            For multiple results: Tuple of (list_of_tuples, None, None) where each tuple is (event_type, data, metadata)
        """
        # Handle list of HandlerResults
        if isinstance(handler_result, list) and handler_result and all(hasattr(item, "event_type") for item in handler_result):
            results = []
            for item in handler_result:
                event_type = item.event_type if hasattr(item, "event_type") else None
                data = item.data if hasattr(item, "data") else None
                metadata = (item.metadata or {}) if hasattr(item, "metadata") else {}
                results.append((event_type, data, metadata))
            return results, None, None

        # Handle single HandlerResult
        event_type_to_publish = None
        result_data_dict = None
        result_metadata = {}

        if handler_result is not None:
            if hasattr(handler_result, "event_type") and hasattr(handler_result, "data"):
                event_type_to_publish = handler_result.event_type
                result_data_dict = handler_result.data
                if hasattr(handler_result, "metadata"):
                    result_metadata = handler_result.metadata or {}
            else:
                result_data_dict = handler_result

        return event_type_to_publish, result_data_dict, result_metadata

    @staticmethod
    def build_result_data(request_id: str, handler_result: Any, event_type_to_publish: str | None) -> dict[str, Any]:
        """
        Build result data dictionary.

        Args:
            request_id: Request identifier
            handler_result: Result from handler
            event_type_to_publish: Event type if publishing

        Returns:
            Result data dictionary
        """
        status = "processed" if handler_result is not None else "no_handler_found"

        result_data = {
            "request_id": request_id,
            "status": status,
            "result": handler_result,
            "metadata": {},
        }

        if handler_result is None:
            result_data["message"] = "No handler processed this event"

        return result_data
