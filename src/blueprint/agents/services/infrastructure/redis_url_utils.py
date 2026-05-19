"""Helpers for handling Redis connection URLs safely.

Kept in a tiny module without a ``redis-py`` dependency so callers that may run
without the optional ``[redis]`` extra installed (e.g. the cache factory on the
disk-fallback path) can still redact credentials before logging.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_UNPARSEABLE_PLACEHOLDER = "<unparseable redis url>"


def _sanitize_redis_url(url: str) -> str:
    """Return ``url`` with any inline userinfo (``user:password@``) stripped.

    Examples:
        ``redis://:secret@host:6379/0`` → ``redis://host:6379/0``
        ``rediss://user:secret@host:6379/0`` → ``rediss://host:6379/0``
        ``redis://host:6379/0`` → unchanged

    If parsing fails for any reason, a generic placeholder is returned rather
    than the original string — that way an unexpected input format can never
    leak credentials through the caller.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return _UNPARSEABLE_PLACEHOLDER

    host = parts.hostname
    if not host:
        return _UNPARSEABLE_PLACEHOLDER

    # IPv6 hostnames must stay bracketed in the netloc so the port delimiter
    # remains unambiguous (e.g. ``[::1]:6379``).
    if ":" in host:
        host = f"[{host}]"

    netloc = f"{host}:{parts.port}" if parts.port is not None else host

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
