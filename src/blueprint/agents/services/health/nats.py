"""Health check provider for NATS connection."""

import asyncio
import logging
from typing import Optional

import nats
from nats.aio.client import Client as NatsClient

from .base import HealthCheckerBase
from ...config import Config
from ...models.api import ComponentHealth

logger = logging.getLogger(__name__)


class NatsHealthChecker(HealthCheckerBase):
    """Health check provider for NATS connection."""

    def __init__(self, config: Config) -> None:
        """Initialize the NATS health checker.
        
        Args:
            config: Application configuration
        """
        self._config = config
        self._nats_client: Optional[NatsClient] = None
        self._nats_url = self._config.get("nats_url", "nats://localhost:4222")
        self._timeout = self._config.get("nats_health_check_timeout", 5.0)

    async def health_check(self) -> ComponentHealth:
        """Check the health of the NATS connection.
        
        Returns:
            ComponentHealth: The health status of the NATS connection
        """
        nats_client = None
        try:
            # Create a new connection for each health check to ensure it's fresh
            nats_client = await nats.connect(
                self._nats_url,
                connect_timeout=self._timeout,
                max_reconnect_attempts=1,
                dont_randomize=True,
                allow_reconnect=False
            )
            
            if not nats_client.is_connected:
                return ComponentHealth(
                    status="unhealthy",
                    message="Failed to connect to NATS server",
                )
                
            server_info = nats_client.connected_url
            return ComponentHealth(
                status="healthy",
                message=f"Connected to NATS server at {server_info}",
            )
            
        except Exception as e:
            logger.warning("NATS health check failed: %s", str(e), exc_info=True)
            return ComponentHealth(
                status="unhealthy",
                message=f"NATS connection error: {str(e)}",
            )
        finally:
            # Always close the connection when we're done
            if nats_client is not None and not nats_client.is_closed:
                await nats_client.close()
    
    async def close(self) -> None:
        """Close the NATS client connection.
        
        This is a no-op since we close connections after each health check.
        """
        pass
