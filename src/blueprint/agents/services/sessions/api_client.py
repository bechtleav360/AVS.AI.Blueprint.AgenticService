"""HTTP client for sessions service REST API.

This module provides the SessionsApiClient for interacting with the sessions
service REST API endpoints. It handles authentication, job lifecycle operations,
and session key management.
"""

import logging
from typing import Any
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

    async def get_job_details(
        self,
        session_id: UUID,
        job_id: UUID,
        session_key: str,
    ) -> dict[str, Any]:
        """Fetch full job details including encrypted payload.

        Args:
            session_id: UUID of the session
            job_id: UUID of the job
            session_key: Session key for decrypting private envelope data

        Returns:
            Job details dictionary with decrypted payload

        Raises:
            httpx.HTTPStatusError: If the request fails
            ValueError: If client not initialized
        """
        if not self._client:
            raise ValueError("SessionsApiClient not initialized. Call on_startup() first.")

        url = f"{self._base_url}/sessions/{session_id}/jobs/{job_id}"
        headers = {"X-Session-Key": session_key}

        logger.debug("Fetching job details: session_id=%s, job_id=%s", session_id, job_id)

        response = await self._client.get(url, headers=headers)
        response.raise_for_status()

        job_data = response.json()
        logger.debug("Job details fetched successfully: job_id=%s", job_id)

        return job_data

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
        if not self._client:
            raise ValueError("SessionsApiClient not initialized. Call on_startup() first.")

        url = f"{self._base_url}/sessions/{session_id}/jobs/{job_id}/start"
        payload = {"agent_id": agent_id}
        headers = {"X-Session-Key": session_key}

        logger.info("Starting job: session_id=%s, job_id=%s, agent_id=%s", session_id, job_id, agent_id)

        response = await self._client.post(url, json=payload, headers=headers)
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
        if not self._client:
            raise ValueError("SessionsApiClient not initialized. Call on_startup() first.")

        url = f"{self._base_url}/sessions/{session_id}/jobs/{job_id}"
        headers = {"X-Session-Key": session_key}

        response = await self._client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

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
        if not self._client:
            raise ValueError("SessionsApiClient not initialized. Call on_startup() first.")

        url = f"{self._base_url}/sessions/{session_id}/jobs/{job_id}/complete"
        headers = {"X-Session-Key": session_key}
        payload = {"result": result}

        logger.info("Completing job: session_id=%s, job_id=%s", session_id, job_id)

        response = await self._client.post(url, json=payload, headers=headers)
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
        if not self._client:
            raise ValueError("SessionsApiClient not initialized. Call on_startup() first.")

        url = f"{self._base_url}/sessions/{session_id}/jobs/{job_id}/cancel"
        headers = {"X-Session-Key": session_key}
        payload = {"reason": reason} if reason else {}

        logger.warning("Cancelling job: session_id=%s, job_id=%s, reason=%s", session_id, job_id, reason)

        response = await self._client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        job_data = response.json()
        logger.info("Job cancelled successfully: job_id=%s", job_id)

        return job_data
