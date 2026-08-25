"""Sessions service integration components.

This module provides all components needed for integrating with the sessions service:
- SessionsApiClient: HTTP client for sessions service REST API
- SessionKeyProvider: Session key management with caching
"""

from .api_client import SessionsApiClient
from .key_provider import SessionKeyClaimConflictError, SessionKeyProvider

__all__ = [
    "SessionKeyClaimConflictError",
    "SessionKeyProvider",
    "SessionsApiClient",
]
