"""Unit tests for the Redis URL sanitizer used in logs and readiness probes."""

from __future__ import annotations

import pytest

from blueprint.agents.services.infrastructure.redis_url_utils import (
    _UNPARSEABLE_PLACEHOLDER,
    _sanitize_redis_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("redis://:secret@host:6379/0", "redis://host:6379/0"),
        ("redis://user:secret@host:6379/0", "redis://host:6379/0"),
        ("rediss://user:secret@host:6379/0", "rediss://host:6379/0"),
        ("redis://host:6379/0", "redis://host:6379/0"),
        ("redis://host/0", "redis://host/0"),
        # IPv6: brackets must survive sanitisation so the port stays parsable.
        ("redis://[::1]:6379/0", "redis://[::1]:6379/0"),
        ("rediss://user:secret@[fe80::1]:6379/0", "rediss://[fe80::1]:6379/0"),
        # Query/fragment survive untouched.
        (
            "redis://user:secret@host:6379/0?ssl_cert_reqs=none#frag",
            "redis://host:6379/0?ssl_cert_reqs=none#frag",
        ),
    ],
)
def test_sanitize_strips_userinfo(raw: str, expected: str) -> None:
    assert _sanitize_redis_url(raw) == expected


def test_sanitize_returns_placeholder_for_unparseable_input() -> None:
    # An empty hostname can't be safely echoed back — fall through to placeholder.
    assert _sanitize_redis_url("not a url") == _UNPARSEABLE_PLACEHOLDER


def test_sanitized_url_never_contains_password() -> None:
    raw = "redis://admin:hunter2@cache.internal:6380/3"
    sanitized = _sanitize_redis_url(raw)
    assert "hunter2" not in sanitized
    assert "admin" not in sanitized
    assert "cache.internal" in sanitized
    assert "6380" in sanitized
