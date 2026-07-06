"""HTTP client for sessions service REST API.

This module provides the SessionsApiClient for interacting with the sessions
service REST API endpoints. It handles authentication, job lifecycle operations,
and session key management.
"""

import logging
from typing import Any, Literal
from uuid import UUID

import httpx

from ..service_base import ServiceBase

logger = logging.getLogger(__name__)


class SessionsApiClient(ServiceBase):
    """HTTP client for sessions service REST API.

    Provides methods to fetch job details, start jobs, complete jobs, and cancel jobs.
    Handles authentication via X-Api-Key header and session key management for
    encrypted payload access.

    Configuration (settings.toml):
        [sessions_service]
        base_url = "http://localhost:8000"
        api_key = "@format {env[SESSIONS_API_KEY]}"
    """

    def __init__(self) -> None:
        super().__init__()
        self._base_url: str | None = None
        self._api_key: str | None = None
        self._client: httpx.AsyncClient | None = None

    async def on_startup(self) -> None:
        """Initialize the HTTP client with configuration."""
        config = self.config.get("sessions_service")
        if not config:
            raise ValueError("sessions_service configuration not found")

        self._base_url = config.get("base_url")
        self._api_key = config.get("api_key")

        if not self._base_url:
            raise ValueError("sessions_service.base_url is required")
        if not self._api_key:
            raise ValueError("sessions_service.api_key is required")

        # Create persistent HTTP client
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers={"X-Api-Key": self._api_key},
        )

        logger.info("SessionsApiClient initialized with base_url=%s", self._base_url)

    async def on_shutdown(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            logger.info("SessionsApiClient HTTP client closed")

    async def _request(
        self,
        method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
        path: str,
        *,
        session_key: str | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Issue an authenticated request to the sessions service.

        Owns the client-initialised guard, URL assembly, and the optional
        X-Session-Key header. Returns the raw Response so callers decide how to treat
        status codes (registration branches on 404 rather than always raising).
        """
        if not self._client:
            raise ValueError("SessionsApiClient not initialized. Call on_startup() first.")

        url = f"{self._base_url}{path}"
        kwargs: dict[str, Any] = {}
        if session_key is not None:
            kwargs["headers"] = {"X-Session-Key": session_key}
        if json is not None:
            kwargs["json"] = json

        method_fn = getattr(self._client, method.lower(), None)
        if method_fn is None:
            raise ValueError(f"Unsupported HTTP method: {method!r}")
        return await method_fn(url, **kwargs)

    async def start_job(
        self,
        session_id: UUID,
        job_id: UUID,
        agent_id: str,
        session_key: str,
    ) -> dict[str, Any]:
        """Mark job as running.

        Args:
            session_id: UUID of the session
            job_id: UUID of the job
            agent_id: ID of the agent starting the job
            session_key: Session key for private envelope access

        Returns:
            Updated job details

        Raises:
            httpx.HTTPStatusError: If the request fails
            ValueError: If client not initialized
        """
        logger.info("Starting job: session_id=%s, job_id=%s, agent_id=%s", session_id, job_id, agent_id)
        response = await self._request(
            "POST",
            f"/sessions/{session_id}/jobs/{job_id}/start",
            session_key=session_key,
            json={"agent_id": agent_id},
        )
        response.raise_for_status()
        job_data = response.json()
        logger.info("Job started successfully: job_id=%s", job_id)
        return job_data

    async def get_job_detail(
        self,
        session_id: UUID,
        job_id: UUID,
        session_key: str,
    ) -> dict[str, Any]:
        """Fetch a single job's full detail.

        Args:
            session_id: UUID of the session
            job_id: UUID of the job
            session_key: Session key for decrypting private envelope data

        Returns:
            Job detail dictionary with decrypted payload

        Raises:
            httpx.HTTPStatusError: If the request fails
            ValueError: If client not initialized
        """
        logger.debug("Fetching job detail: session_id=%s, job_id=%s", session_id, job_id)
        response = await self._request(
            "GET",
            f"/sessions/{session_id}/jobs/{job_id}",
            session_key=session_key,
        )
        response.raise_for_status()
        job_data = response.json()
        logger.debug("Job detail fetched: job_id=%s", job_id)
        return job_data

    async def complete_job(
        self,
        session_id: UUID,
        job_id: UUID,
        session_key: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit job results and mark as completed.

        Args:
            session_id: UUID of the session
            job_id: UUID of the job
            session_key: Session key for encrypting result data
            result: Job result data to submit

        Returns:
            Updated job details

        Raises:
            httpx.HTTPStatusError: If the request fails
            ValueError: If client not initialized
        """
        logger.info("Completing job: session_id=%s, job_id=%s", session_id, job_id)
        response = await self._request(
            "POST",
            f"/sessions/{session_id}/jobs/{job_id}/complete",
            session_key=session_key,
            json={"result": result},
        )
        response.raise_for_status()
        job_data = response.json()
        logger.info("Job completed successfully: job_id=%s", job_id)
        return job_data

    async def cancel_job(
        self,
        session_id: UUID,
        job_id: UUID,
        session_key: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Cancel a job.

        Args:
            session_id: UUID of the session
            job_id: UUID of the job
            session_key: Session key for authentication
            reason: Optional reason for cancellation

        Returns:
            Updated job details

        Raises:
            httpx.HTTPStatusError: If the request fails
            ValueError: If client not initialized
        """
        payload = {"reason": reason} if reason else {}
        logger.warning("Cancelling job: session_id=%s, job_id=%s, reason=%s", session_id, job_id, reason)
        response = await self._request(
            "POST",
            f"/sessions/{session_id}/jobs/{job_id}/cancel",
            session_key=session_key,
            json=payload,
        )
        response.raise_for_status()
        job_data = response.json()
        logger.info("Job cancelled successfully: job_id=%s", job_id)
        return job_data

    async def register_agent(
        self,
        agent_id: str,
        agent_type: str | None,
        capabilities: list[str],
        version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Register the agent with the sessions dispatch registry (idempotent).

        v0.4.0 gates ``GET /jobs/stream/sse`` on a prior registration. Returns True
        when the server accepted it (200/201). Returns False when the server is a
        legacy (< v0.4.0) instance without the endpoint (404) — the caller may still
        open the stream. Raises on any other non-2xx so the reconnect loop backs off.

        ``agent_type`` is omitted from the payload when ``None`` (as with ``version``
        and ``metadata``); the server rejects a missing required field loudly rather
        than silently accepting an empty string.
        """
        payload: dict[str, Any] = {"agent_id": agent_id, "capabilities": capabilities}
        if agent_type is not None:
            payload["agent_type"] = agent_type
        if version is not None:
            payload["version"] = version
        if metadata:
            payload["metadata"] = metadata

        response = await self._request("POST", "/agents/register", json=payload)

        if response.status_code == 404:
            logger.warning("Sessions service has no /agents/register (legacy < v0.4.0); proceeding without registration")
            return False

        if response.status_code >= 400:
            logger.error("Agent registration failed: status=%d body=%s", response.status_code, response.text)
        response.raise_for_status()
        logger.info("Agent registered: agent_id=%s (status=%d)", agent_id, response.status_code)
        return True

    async def unregister_agent(self, agent_id: str) -> None:
        """Best-effort graceful deregistration (idempotent DELETE). Never raises.

        Called on shutdown; a failure here must not prevent a clean shutdown, so all
        exceptions (network error, 404 on legacy, closed client) are swallowed.
        """
        try:
            response = await self._request("DELETE", f"/agents/{agent_id}")
            logger.info("Agent unregistered: agent_id=%s (status=%d)", agent_id, response.status_code)
        except Exception as e:
            logger.warning("Graceful unregister failed for agent_id=%s: %s", agent_id, e)
