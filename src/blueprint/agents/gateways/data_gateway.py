"""Data Gateway client for fetching asset metadata."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

# Note: get_data_gateway_config and AssetMetadata are not yet implemented
# This module is a stub for future data gateway integration

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class DataGatewayError(Exception):
    """Base exception for data gateway errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        is_transient: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.is_transient = is_transient


class CircuitBreakerError(DataGatewayError):
    """Circuit breaker is open."""

    def __init__(self, message: str = "Circuit breaker is open"):
        super().__init__(message, is_transient=True)


class CircuitBreaker:
    """Simple circuit breaker implementation."""

    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.failure_count = 0
        self.last_failure_time: datetime | None = None
        self.state = "closed"  # closed, open, half-open

    def is_open(self) -> bool:
        """Check if circuit breaker is open."""
        if self.state == "open":
            if self.last_failure_time and datetime.utcnow() - self.last_failure_time > timedelta(seconds=self.timeout_seconds):
                self.state = "half-open"
                return False
            return True
        return False

    def record_success(self):
        """Record a successful operation."""
        self.failure_count = 0
        self.state = "closed"
        self.last_failure_time = None

    def record_failure(self):
        """Record a failed operation."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


class DataGatewayClient:
    """Client for fetching asset data from the data gateway."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the data gateway client."""
        if config is None:
            raise ValueError("DataGatewayClient requires a config dict. get_data_gateway_config() is not yet implemented.")

        self.config = config
        self.base_url = self.config["base_url"].rstrip("/")
        self.timeout = self.config["timeout"]
        self.api_key = self.config.get("api_key")

        # Retry configuration
        self.max_attempts = self.config["retry_max_attempts"]
        self.backoff_factor = self.config["retry_backoff_factor"]

        # Circuit breaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config["circuit_breaker_failure_threshold"],
            timeout_seconds=self.config["circuit_breaker_timeout_s"],
        )

        # HTTP client
        headers = {"User-Agent": "asset-backup-checker/0.1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers=headers,
            follow_redirects=True,
        )

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def get_asset(self, asset_id: str, traceparent: str | None = None) -> dict[str, Any]:
        """
        Fetch asset metadata by ID.

        Args:
            asset_id: The asset identifier
            traceparent: W3C trace context for distributed tracing

        Returns:
            AssetMetadata object

        Raises:
            DataGatewayError: If the asset cannot be fetched
        """
        with tracer.start_as_current_span("data_gateway.get_asset") as span:
            span.set_attribute("asset_id", asset_id)

            # Check circuit breaker
            if self.circuit_breaker.is_open():
                span.set_status(Status(StatusCode.ERROR, "Circuit breaker open"))
                raise CircuitBreakerError()

            # Prepare headers
            headers = {}
            if traceparent:
                headers["traceparent"] = traceparent

            # Build URL
            url = urljoin(self.base_url, f"/assets/{asset_id}")
            span.set_attribute("gateway_url", url)

            # Retry logic
            last_exception = None
            for attempt in range(self.max_attempts):
                try:
                    span.set_attribute("attempt", attempt + 1)

                    # Make request
                    response = await self.client.get(url, headers=headers)

                    # Handle response
                    if response.status_code == 200:
                        data = response.json()

                        # Record success
                        self.circuit_breaker.record_success()
                        span.set_status(Status(StatusCode.OK))
                        if isinstance(data, dict):
                            span.set_attribute("asset_type", data.get("type", "unknown"))
                            span.set_attribute("asset_provider", data.get("provider", "unknown"))

                        logger.info(f"Successfully fetched asset {asset_id}")
                        return data

                    elif response.status_code == 404:
                        # Asset not found - permanent error
                        span.set_status(Status(StatusCode.ERROR, "Asset not found"))
                        raise DataGatewayError(
                            f"Asset {asset_id} not found",
                            status_code=404,
                            is_transient=False,
                        )

                    elif response.status_code in (401, 403):
                        # Authentication/authorization error - permanent
                        span.set_status(Status(StatusCode.ERROR, "Authentication failed"))
                        raise DataGatewayError(
                            f"Authentication failed: {response.status_code}",
                            status_code=response.status_code,
                            is_transient=False,
                        )

                    elif response.status_code >= 500:
                        # Server error - transient
                        error_msg = f"Server error: {response.status_code}"
                        last_exception = DataGatewayError(
                            error_msg,
                            status_code=response.status_code,
                            is_transient=True,
                        )
                        logger.warning(f"Attempt {attempt + 1} failed: {error_msg}")

                    else:
                        # Other client errors - permanent
                        span.set_status(
                            Status(
                                StatusCode.ERROR,
                                f"Client error: {response.status_code}",
                            )
                        )
                        raise DataGatewayError(
                            f"Client error: {response.status_code}",
                            status_code=response.status_code,
                            is_transient=False,
                        )

                except httpx.TimeoutException as e:
                    last_exception = DataGatewayError(f"Request timeout: {e}", is_transient=True)
                    logger.warning(f"Attempt {attempt + 1} timed out")

                except httpx.NetworkError as e:
                    last_exception = DataGatewayError(f"Network error: {e}", is_transient=True)
                    logger.warning(f"Attempt {attempt + 1} network error: {e}")

                except Exception as e:
                    last_exception = DataGatewayError(f"Unexpected error: {e}", is_transient=False)
                    logger.error(f"Attempt {attempt + 1} unexpected error: {e}")
                    break  # Don't retry unexpected errors

                # Wait before retry (exponential backoff)
                if attempt < self.max_attempts - 1:
                    wait_time = self.backoff_factor**attempt
                    logger.info(f"Waiting {wait_time}s before retry {attempt + 2}")
                    await asyncio.sleep(wait_time)

            # All attempts failed
            self.circuit_breaker.record_failure()
            span.set_status(Status(StatusCode.ERROR, "All retry attempts failed"))

            if last_exception:
                raise last_exception
            else:
                raise DataGatewayError(f"Failed to fetch asset {asset_id} after {self.max_attempts} attempts")

    async def health_check(self) -> dict[str, Any]:
        """
        Check the health of the data gateway.

        Returns:
            Health status information
        """
        with tracer.start_as_current_span("data_gateway.health_check") as span:
            try:
                url = urljoin(self.base_url, "/health")
                response = await self.client.get(url, timeout=5.0)

                if response.status_code == 200:
                    span.set_status(Status(StatusCode.OK))
                    return {
                        "status": "healthy",
                        "response_time_ms": response.elapsed.total_seconds() * 1000,
                        "circuit_breaker_state": self.circuit_breaker.state,
                    }
                else:
                    span.set_status(
                        Status(
                            StatusCode.ERROR,
                            f"Health check failed: {response.status_code}",
                        )
                    )
                    return {
                        "status": "unhealthy",
                        "error": f"HTTP {response.status_code}",
                        "circuit_breaker_state": self.circuit_breaker.state,
                    }

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                return {
                    "status": "unhealthy",
                    "error": str(e),
                    "circuit_breaker_state": self.circuit_breaker.state,
                }

    async def get_asset_by_url(self, asset_url: str, traceparent: str | None = None) -> dict[str, Any]:
        """
        Fetch asset metadata by URL (for thin events with asset_url).

        Args:
            asset_url: Full URL to the asset
            traceparent: W3C trace context for distributed tracing

        Returns:
            AssetMetadata object
        """
        with tracer.start_as_current_span("data_gateway.get_asset_by_url") as span:
            span.set_attribute("asset_url", asset_url)

            # Check circuit breaker
            if self.circuit_breaker.is_open():
                span.set_status(Status(StatusCode.ERROR, "Circuit breaker open"))
                raise CircuitBreakerError()

            # Prepare headers
            headers = {}
            if traceparent:
                headers["traceparent"] = traceparent

            # Retry logic (similar to get_asset)
            last_exception = None
            for attempt in range(self.max_attempts):
                try:
                    span.set_attribute("attempt", attempt + 1)

                    response = await self.client.get(asset_url, headers=headers)

                    if response.status_code == 200:
                        data = response.json()

                        self.circuit_breaker.record_success()
                        span.set_status(Status(StatusCode.OK))

                        logger.info(f"Successfully fetched asset from URL {asset_url}")
                        return data

                    elif response.status_code == 404:
                        span.set_status(Status(StatusCode.ERROR, "Asset not found"))
                        raise DataGatewayError(
                            f"Asset not found at URL {asset_url}",
                            status_code=404,
                            is_transient=False,
                        )

                    elif response.status_code >= 500:
                        error_msg = f"Server error: {response.status_code}"
                        last_exception = DataGatewayError(
                            error_msg,
                            status_code=response.status_code,
                            is_transient=True,
                        )
                        logger.warning(f"Attempt {attempt + 1} failed: {error_msg}")

                    else:
                        span.set_status(
                            Status(
                                StatusCode.ERROR,
                                f"Client error: {response.status_code}",
                            )
                        )
                        raise DataGatewayError(
                            f"Client error: {response.status_code}",
                            status_code=response.status_code,
                            is_transient=False,
                        )

                except httpx.TimeoutException as e:
                    last_exception = DataGatewayError(f"Request timeout: {e}", is_transient=True)
                    logger.warning(f"Attempt {attempt + 1} timed out")

                except httpx.NetworkError as e:
                    last_exception = DataGatewayError(f"Network error: {e}", is_transient=True)
                    logger.warning(f"Attempt {attempt + 1} network error: {e}")

                except Exception as e:
                    last_exception = DataGatewayError(f"Unexpected error: {e}", is_transient=False)
                    logger.error(f"Attempt {attempt + 1} unexpected error: {e}")
                    break

                # Wait before retry
                if attempt < self.max_attempts - 1:
                    wait_time = self.backoff_factor**attempt
                    await asyncio.sleep(wait_time)

            # All attempts failed
            self.circuit_breaker.record_failure()
            span.set_status(Status(StatusCode.ERROR, "All retry attempts failed"))

            if last_exception:
                raise last_exception
            else:
                raise DataGatewayError(f"Failed to fetch asset from URL {asset_url} after {self.max_attempts} attempts")
