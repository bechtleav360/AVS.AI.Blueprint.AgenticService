"""Factory for selecting the appropriate cache backend from configuration."""

import logging
import re
from pathlib import PurePosixPath

from blueprint.agents.component.registry import DEFAULT_CACHE_NAME
from blueprint.agents.models.config import CacheConfig
from blueprint.agents.services.infrastructure.redis_url_utils import _sanitize_redis_url
from blueprint.agents.services.infrastructure.cache_service import CacheService

logger = logging.getLogger(__name__)

_ALLOWED_CACHE_NAME = re.compile(r"\A[a-z0-9][a-z0-9_.-]*\Z")
"""What a cache name may look like. See :meth:`CacheBackendFactory.validate_name`."""


class CacheBackendFactory:
    """Instantiates the correct CacheService implementation based on CacheConfig.backend.

    **A cache name is turned into isolated storage here**, in the same place the backend is
    chosen, and that is deliberate rather than incidental. A process may hold several caches
    registered under different names (spec sec. 8), and two of them sharing one store are one
    cache under two names -- with the name, the only thing meant to tell them apart, quietly
    doing nothing. How a backend isolates is knowledge only the backend has: the disk cache
    separates by directory, Redis by key prefix, and a future backend by something else again.
    So each ``_create_*`` scopes what its own backend needs, and adding a backend means
    answering that question in the method that creates it -- not discovering later that a
    caller somewhere else was supposed to have answered it.
    """

    @staticmethod
    def create(config: CacheConfig, enable_locking: bool = True, name: str = DEFAULT_CACHE_NAME) -> CacheService:
        """Create the cache called ``name``, on the backend ``config`` selects.

        Args:
            config: The application's cache configuration, as loaded. It is *not* pre-scoped:
                scoping is per backend and happens below.
            enable_locking: File-based locking, for the disk backend.
            name: Which cache this is. :data:`DEFAULT_CACHE_NAME` reproduces exactly what a
                single-cache application has always got -- same directory, same Redis
                keyspace, same registry name.

        Returns:
            The cache service, already registered in the component registry under the name
            :meth:`_component_name` derives.

        Raises:
            ValueError: if ``name`` cannot serve as a cache name.
        """
        CacheBackendFactory.validate_name(name)
        if config.backend == "redis":
            return CacheBackendFactory._create_redis(config, enable_locking, name)
        return CacheBackendFactory._create_disk(config, enable_locking, name)

    @staticmethod
    def validate_name(name: str) -> None:
        """Reject a cache name that cannot serve as one.

        The name becomes a filesystem path segment and a segment of a Redis key prefix, so
        ``"../evil"`` would write outside the configured cache directory. Lower case only, and
        not for tidiness: a directory whose name differs only by case is one directory on a
        developer's machine and two on a Linux node, so ``Sessions`` and ``sessions`` would be
        one cache locally and two in production.

        Raises:
            ValueError: if ``name`` is outside the allowed alphabet.
        """
        if not _ALLOWED_CACHE_NAME.match(name):
            raise ValueError(
                f"Cache name {name!r} is not a legal cache name: it must match [a-z0-9][a-z0-9_.-]*. A cache name "
                "becomes a directory under the configured cache_dir and a segment of the Redis key prefix, so it "
                "cannot contain a path separator, and it is lower-case only because two names differing by case are "
                "one directory on a case-insensitive filesystem and two on Linux."
            )

    @staticmethod
    def _component_name(name: str) -> str | None:
        """Return the registry name the cache service registers under, or ``None`` to derive it.

        A cache service is a ``Component``, so two of them would collide on the one name derived
        from their class. The default cache keeps that derived name -- ``disk_cache_service`` --
        because existing lookups and health entries already use it.

        ``cache_<name>`` rather than ``<class>_<name>`` because ``fallback_to_local`` can swap
        ``RedisCacheService`` for ``DiskCacheService`` at construction: a registry key that
        depends on whether Redis answered the startup ping is worse than one that does not name
        the backend at all.
        """
        return None if name == DEFAULT_CACHE_NAME else f"cache_{name}"

    @staticmethod
    def _scoped_cache_dir(config: CacheConfig, name: str) -> str:
        """Return the directory the disk cache called ``name`` stores in.

        ``<cache_dir>/<name>`` -- a *subdirectory* of the configured directory and not a sibling
        of it, which is the only form that is always writable. A deployment may mount its volume
        at ``cache.cache_dir`` itself, and under ``readOnlyRootFilesystem`` nothing outside the
        mount can be created; see "Writable Cache Directory" in ``docs/guides/deployment.md``.
        The cost is that a named cache's directory sits inside the default cache's own store.
        diskcache ignores directories it did not create, and the alternative is a path that
        fails in production only.
        """
        if name == DEFAULT_CACHE_NAME:
            return config.cache_dir
        return str(PurePosixPath(config.cache_dir.replace("\\", "/")) / name)

    @staticmethod
    def _scoped_key_prefix(config: CacheConfig, name: str) -> str:
        """Return the Redis key prefix the cache called ``name`` writes under.

        On Redis the prefix is the whole of the separation: ``RedisCacheService`` scopes every
        key by ``key_prefix`` and nothing else, so two caches named ``sessions`` and ``prompts``
        against one Redis with one configured prefix would write the same keys. The disk
        backend's directory has no analogue here, so without this the name would isolate
        nothing at all.
        """
        if name == DEFAULT_CACHE_NAME:
            return config.key_prefix
        return f"{config.key_prefix}:{name}" if config.key_prefix else name

    @staticmethod
    def _create_redis(config: CacheConfig, enable_locking: bool, name: str = DEFAULT_CACHE_NAME) -> CacheService:
        try:
            from blueprint.agents.services.infrastructure.redis_cache_service import RedisCacheService
        except ImportError as e:
            if config.fallback_to_local:
                logger.warning("Redis extra not installed, falling back to DiskCacheService: %s", e)
                return CacheBackendFactory._create_disk(config, enable_locking, name)
            raise

        resolved_url = config.redis_url or "redis://localhost:6379/0"

        service = RedisCacheService(
            redis_url=resolved_url,
            password=config.redis_password,
            db=config.redis_db,
            tls=config.redis_tls,
            key_prefix=CacheBackendFactory._scoped_key_prefix(config, name),
            default_ttl=config.default_ttl,
            fallback_to_local=config.fallback_to_local,
            component_name=CacheBackendFactory._component_name(name),
        )

        # Probe the connection synchronously so a "RedisCacheService" instance
        # always implies a reachable Redis. If the probe fails and the caller
        # opted in to local fallback, swap to DiskCacheService here — the
        # alternative (failing later in on_startup) leaves us with a registered
        # service whose operations silently no-op.
        try:
            service._client.ping()
        except Exception as e:
            service.close()
            if config.fallback_to_local:
                logger.warning(
                    "Redis at %s unreachable, falling back to DiskCacheService: %s",
                    _sanitize_redis_url(resolved_url),
                    e,
                )
                # The unscoped config plus the name, never the redis-scoped one: the fallback is
                # a different backend and needs its own isolation -- a directory, not a prefix.
                return CacheBackendFactory._create_disk(config, enable_locking, name)
            raise

        return service

    @staticmethod
    def _create_disk(config: CacheConfig, enable_locking: bool = True, name: str = DEFAULT_CACHE_NAME) -> CacheService:
        from blueprint.agents.services.infrastructure.cache_service import DiskCacheService

        return DiskCacheService(
            cache_dir=CacheBackendFactory._scoped_cache_dir(config, name),
            size_limit=config.size_limit,
            eviction_policy=config.eviction_policy,
            enable_locking=enable_locking,
            default_ttl=config.default_ttl,
            component_name=CacheBackendFactory._component_name(name),
        )
