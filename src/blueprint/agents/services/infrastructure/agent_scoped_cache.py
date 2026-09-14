"""A per-agent lens on one shared cache backend (spec sec. 8)."""

import logging
from collections.abc import Iterator
from typing import Any

from .cache_service import CacheService

logger = logging.getLogger(__name__)

AGENT_SEPARATOR = "."
"""Separates the agent from the partition it asked for, inside one cache.

A ``.`` rather than a ``:`` because ``:`` is already the separator between the partition and the
hashed key (``cache_key_mixin._make_key``), and ``list_namespaces`` splits on the first one -- so
a ``:`` here would make ``orders:prices`` read back as the partition ``orders``. A namespace
cannot contain ``.`` (its alphabet is ``[a-z][a-z0-9_]*``), so stripping ``<agent>.`` back off is
unambiguous whatever the agent called its own partition.
"""


class AgentScopedCache(CacheService):
    """One agent's view of a shared cache, isolating its keys from its neighbours'.

    Spec sec. 8: two independently written agents both storing under ``"sessions"`` must not
    share a store the moment they are grouped. This is what enforces that, and it does so
    *without a second backend*: every call has its partition prefixed with the agent's
    namespace, so ``orders`` writing ``sessions`` lands in ``orders.sessions`` and ``billing``
    writing the same name lands in ``billing.sessions``.

    **Why prefix the partition rather than register a cache per agent.** A cache backend is a
    filesystem directory (``DiskCacheService``) or a connection (``RedisCacheService``). One
    backend per agent per name would multiply both, and on Kubernetes the directory is the
    binding constraint: a pod with a read-only root filesystem can write only where a volume is
    mounted, and that mount is declared in the pod spec, not discovered at runtime. Prefixing
    keys means grouping agents changes no path, needs no additional mount, and keeps one
    ``size_limit`` budget over one volume rather than N budgets over one.

    The agent never sees this. ``Component.registry`` hands a namespaced component its
    namespace's registry view, and that view's ``get_cache`` returns this object, so a service
    writing ``self.registry.cache_service.set(key, value, namespace="prices")`` is isolated
    without naming a namespace. A **root** component gets the raw backend, which is also the
    opt-in for a deliberately shared cache.
    """

    def __init__(self, cache: CacheService, agent: str) -> None:
        """Wrap ``cache`` for ``agent``.

        Args:
            cache: The shared backend. Not owned: this object never closes it.
            agent: The namespace to prefix partitions with. Must not be empty -- the root
                namespace uses the backend directly, so wrapping it would add a ``.`` prefix
                that changes where an existing single-agent application's keys live.

        Raises:
            ValueError: if ``agent`` is empty.
        """
        if not agent:
            raise ValueError(
                "AgentScopedCache needs an agent namespace: the root namespace reads the cache backend directly, and "
                "wrapping it would move every key of an existing application."
            )
        super().__init__(name=f"{agent}_scoped_cache", should_register=False)
        self._cache = cache
        self._agent = agent

    @property
    def agent(self) -> str:
        """The namespace whose keys this view reads and writes."""
        return self._agent

    @property
    def backend(self) -> CacheService:
        """The shared cache underneath, for the framework code that owns it."""
        return self._cache

    def _scoped(self, namespace: str) -> str:
        """Return the partition ``namespace`` becomes for this agent."""
        return f"{self._agent}{AGENT_SEPARATOR}{namespace}"

    def _owns(self, namespace: str) -> bool:
        """Whether a partition in the shared cache belongs to this agent."""
        return namespace.startswith(f"{self._agent}{AGENT_SEPARATOR}")

    async def on_startup(self) -> None:
        """Nothing to start: the backend is started by whoever registered it."""

    async def on_shutdown(self) -> None:
        """Nothing to stop: the backend outlives any one agent's view of it."""

    def get(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> Any | None:
        return self._cache.get(key, self._scoped(namespace))

    def set(
        self,
        key: str | list[str] | dict[str, Any],
        value: Any,
        namespace: str = "default",
        ttl: int | None = None,
    ) -> None:
        self._cache.set(key, value, self._scoped(namespace), ttl)

    def delete(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        return self._cache.delete(key, self._scoped(namespace))

    def exists(self, key: str | list[str] | dict[str, Any], namespace: str = "default") -> bool:
        return self._cache.exists(key, self._scoped(namespace))

    def claim(self, key: str | list[str] | dict[str, Any], value: Any, namespace: str = "default", ttl: int | None = None) -> bool:
        return self._cache.claim(key, value, self._scoped(namespace), ttl)

    def clear(self, namespace: str | None = None) -> None:
        """Clear one of this agent's partitions, or all of them.

        ``None`` means *this agent's* partitions, never the whole cache -- the backend's own
        ``clear(None)`` would take its neighbours' data with it, which is the accident this
        class exists to prevent.
        """
        if namespace is not None:
            self._cache.clear(self._scoped(namespace))
            return
        for owned in (name for name in self._cache.list_namespaces() if self._owns(name)):
            self._cache.clear(owned)

    def list_namespaces(self) -> list[str]:
        """This agent's partitions, named as it named them."""
        prefix = f"{self._agent}{AGENT_SEPARATOR}"
        return [name.removeprefix(prefix) for name in self._cache.list_namespaces() if self._owns(name)]

    def list_values(self, namespace: str = "default", limit: int = 100, offset: int = 0) -> Iterator[Any]:
        return self._cache.list_values(self._scoped(namespace), limit, offset)

    def get_stats(self) -> dict[str, Any]:
        """The backend's statistics, which are process-wide rather than per agent.

        Size, hit counts and eviction are properties of the one store every agent shares, so
        there is nothing per-agent to report and nothing gained by pretending otherwise. The
        agent is named in the result so a reader knows whose view produced it.
        """
        return {**self._cache.get_stats(), "agent": self._agent}

    def hash(self, value: str | list[str] | dict[str, Any]) -> str:
        return self._cache.hash(value)

    def close(self) -> None:
        """Refuse: the backend belongs to the process, not to one agent.

        Closing it here would take every other agent's cache down with it, and the caller would
        have no way to know it had happened.

        Raises:
            RuntimeError: always.
        """
        raise RuntimeError(
            f"Namespace '{self._agent}' tried to close the cache, which is shared with every other agent in this "
            "process. The application closes it, through the registry that owns it."
        )
