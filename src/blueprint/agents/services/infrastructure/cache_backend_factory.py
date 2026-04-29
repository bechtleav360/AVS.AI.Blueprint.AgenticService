"""Factory for selecting the appropriate cache backend from configuration."""

import logging

from blueprint.agents.models.config import CacheConfig
from blueprint.agents.services.infrastructure.cache_service import CacheService

logger = logging.getLogger(__name__)


class CacheBackendFactory:
    """Instantiates the correct CacheService implementation based on CacheConfig.backend."""

    @staticmethod
    def create(config: CacheConfig, enable_locking: bool = True) -> CacheService:
        if config.backend == "redis":
            return CacheBackendFactory._create_redis(config)
        return CacheBackendFactory._create_disk(config, enable_locking)

    @staticmethod
    def _create_redis(config: CacheConfig) -> CacheService:
        try:
            from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService

            return RedisCacheService(
                redis_url=config.redis_url or "redis://localhost:6379/0",
                password=config.redis_password,
                db=config.redis_db,
                tls=config.redis_tls,
                key_prefix=config.key_prefix,
                default_ttl=config.default_ttl,
                fallback_to_local=config.fallback_to_local,
            )
        except ImportError as e:
            if config.fallback_to_local:
                logger.warning("Redis extra not installed, falling back to DiskCacheService: %s", e)
                return CacheBackendFactory._create_disk(config)
            raise

    @staticmethod
    def _create_disk(config: CacheConfig, enable_locking: bool = True) -> CacheService:
        from blueprint.agents.services.infrastructure.cache_service import DiskCacheService

        return DiskCacheService(
            cache_dir=config.cache_dir,
            size_limit=config.size_limit,
            eviction_policy=config.eviction_policy,
            enable_locking=enable_locking,
        )
