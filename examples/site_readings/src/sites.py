"""Per-run site settings, set by the connection source's ``run_scope`` and read by the service.

This is the one place the agent's code meets the deployment: the source decides which site a run
belongs to (from the connection it arrived on) and opens that site's settings around the run. Each
run starts in an empty context, so a run can only ever see its own site's settings.
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class SiteSettings:
    """What differs per site. Here: where an alert starts."""

    name: str
    alert_threshold: float


_CURRENT: ContextVar[SiteSettings | None] = ContextVar("site_readings_current_site", default=None)


def current_site() -> SiteSettings:
    """The settings of the site the current run belongs to.

    Raises:
        LookupError: outside a run from a named connection -- a reading without a site has no threshold.
    """
    settings = _CURRENT.get()
    if settings is None:
        raise LookupError("No site in scope: readings are only processed in runs from a site's connection.")
    return settings


def enter_site(settings: SiteSettings) -> Token[SiteSettings | None]:
    """Set the current site; returns the token for :func:`leave_site`. Used by the source only."""
    return _CURRENT.set(settings)


def leave_site(token: Token[SiteSettings | None]) -> None:
    """Restore what was current before :func:`enter_site`."""
    _CURRENT.reset(token)
