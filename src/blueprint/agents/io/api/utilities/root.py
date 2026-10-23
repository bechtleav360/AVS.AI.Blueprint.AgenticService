"""Root endpoints providing service metadata."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from ..rest_api_base import RestApiBase

_HTTP_METHODS = frozenset({"GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"})
"""Keys of an OpenAPI path item that are operations; the others (``parameters``, ...) are not."""


class RootApi(RestApiBase):
    """Exposes a root endpoint listing service metadata and all registered routes."""

    def __init__(self, app: FastAPI) -> None:
        """Initialize RootApi."""
        super().__init__(should_register=False)
        self._app = app
        self._html_cache: str | None = None

    async def on_startup(self) -> None:
        """No startup actions required."""

    async def on_shutdown(self) -> None:
        """No shutdown actions required."""

    @RestApiBase.get("/", summary="Service metadata", tags=["root"], response_class=HTMLResponse)
    async def root(self) -> Any:
        """Return an HTML page listing service metadata and all registered endpoints."""
        if self._html_cache is not None:
            return self._html_cache

        service_name = self.config.get("app_name") or "agent-service"
        service_version = self.config.get("app_version") or "0.0.0"
        service_description = self.config.get("app_description") or "Generic microservice blueprint for building intelligent agents"

        docs_url = getattr(self._app, "docs_url", None)
        redoc_url = getattr(self._app, "redoc_url", None)

        doc_links = " | ".join(f'<a href="{url}">{label}</a>' for label, url in [("Swagger UI", docs_url), ("ReDoc", redoc_url)] if url)

        rows = []
        for path, route_methods, summary in self._operations():
            methods = ", ".join(sorted(route_methods))
            if "GET" in route_methods:
                path_cell = f'<a href="{path}">{path}</a>'
            else:
                anchor = path.replace("/", "-").strip("-")
                path_cell = f'<a href="{docs_url}#{anchor}" title="Open in Swagger">{path}</a>' if docs_url else path
            rows.append(f"<tr><td>{methods}</td><td>{path_cell}</td><td>{summary}</td></tr>")

        rows_html = "\n".join(rows)

        self._html_cache = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{service_name}</title>
    <style>
        body {{ font-family: sans-serif; max-width: 900px; margin: 2rem auto; color: #333; }}
        h1 {{ margin-bottom: 0.25rem; }}
        p.desc {{ color: #666; margin-top: 0.25rem; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 1.5rem; }}
        th {{ background: #f4f4f4; text-align: left; padding: 0.5rem 0.75rem; border-bottom: 2px solid #ddd; }}
        td {{ padding: 0.4rem 0.75rem; border-bottom: 1px solid #eee; }}
        a {{ color: #0066cc; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .docs {{ margin-top: 0.5rem; font-size: 0.9rem; }}
    </style>
</head>
<body>
    <h1>{service_name} <small style="font-size:0.5em; color:#999">v{service_version}</small></h1>
    <p class="desc">{service_description}</p>
    <div class="docs">Documentation: {doc_links}</div>
    <table>
        <thead><tr><th>Methods</th><th>Path</th><th>Summary</th></tr></thead>
        <tbody>
{rows_html}
        </tbody>
    </table>
</body>
</html>"""
        return self._html_cache

    def _operations(self) -> list[tuple[str, set[str], str]]:
        """Return ``(path, methods, summary)`` for every documented operation, in schema order.

        Read from the OpenAPI schema rather than from ``app.routes``: since FastAPI 0.137,
        ``include_router()`` leaves a lazy wrapper in ``app.routes`` instead of the routes
        themselves, so every route of an included router -- which is every route this framework
        mounts -- was missing from the table (#42). The schema is FastAPI's public view of the same
        routes, under every version this package supports. It omits routes declared with
        ``include_in_schema=False``, which the table therefore no longer lists either.

        Operations on one path with the same summary share a row, as one route declared with
        several methods always did.
        """
        rows: dict[tuple[str, str], set[str]] = {}
        for path, operations in self._app.openapi().get("paths", {}).items():
            for method, operation in operations.items():
                if method.upper() not in _HTTP_METHODS:
                    continue
                rows.setdefault((path, operation.get("summary") or ""), set()).add(method.upper())
        return [(path, methods, summary) for (path, summary), methods in rows.items()]
