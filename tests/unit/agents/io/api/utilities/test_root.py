"""Unit tests for RootApi."""

from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from starlette.responses import PlainTextResponse

from blueprint.agents.io.api.utilities.root import RootApi

# ---------------------------------------------------------------------------
# Reusable route fixtures
# ---------------------------------------------------------------------------


async def _endpoint() -> None:
    """Minimal async callable for building test routes."""


_GET_ROUTE = ("/items", ["GET"], "List items")
_POST_ROUTE = ("/data", ["POST"], "Create data")


def _make_app(
    *, docs_url: str | None = "/docs", redoc_url: str | None = "/redoc", routes: list[tuple[str, list[str], str]] | None = None
) -> FastAPI:
    """A real application whose routes come from an included router, as AppBuilder mounts them."""
    app = FastAPI(docs_url=docs_url, redoc_url=redoc_url)
    router = APIRouter()
    for path, methods, summary in routes or []:
        router.add_api_route(path, _endpoint, methods=methods, summary=summary)
    app.include_router(router)
    return app


@pytest.fixture
def root_api(mock_config: MagicMock, mock_registry: MagicMock) -> RootApi:
    mock_config.get.side_effect = lambda key, default=None: {
        "app_name": "test-service",
        "app_version": "2.0.0",
        "app_description": "A test description",
    }.get(key, default)
    return RootApi(app=_make_app())


# ---------------------------------------------------------------------------
# HTML content — service metadata
# ---------------------------------------------------------------------------


class TestHtmlContent:
    async def test_service_name_version_description_in_html(self, root_api: RootApi) -> None:
        html = await root_api.root()
        assert "test-service" in html
        assert "2.0.0" in html
        assert "A test description" in html

    async def test_default_values_used_when_config_returns_none(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = None
        api = RootApi(app=_make_app())
        html = await api.root()
        assert "agent-service" in html
        assert "0.0.0" in html

    async def test_both_doc_links_present_when_both_urls_set(self, root_api: RootApi) -> None:
        html = await root_api.root()
        assert 'href="/docs"' in html
        assert 'href="/redoc"' in html

    async def test_swagger_link_omitted_when_docs_url_is_none(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        api = RootApi(app=_make_app(docs_url=None))
        html = await api.root()
        assert "Swagger UI" not in html
        assert "ReDoc" in html

    async def test_redoc_link_omitted_when_redoc_url_is_none(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        api = RootApi(app=_make_app(redoc_url=None))
        html = await api.root()
        assert "ReDoc" not in html
        assert "Swagger UI" in html


# ---------------------------------------------------------------------------
# Route table rendering
# ---------------------------------------------------------------------------


class TestRouteRendering:
    async def test_non_api_route_objects_are_skipped(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        app = _make_app()
        app.add_route("/plain", lambda request: PlainTextResponse("x"))  # a Starlette route, not an APIRoute
        api = RootApi(app=app)
        html = await api.root()
        tbody = html.split("<tbody>")[1].split("</tbody>")[0]
        assert "<tr>" not in tbody

    async def test_routes_of_a_prefixed_included_router_are_listed(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        # #42: since FastAPI 0.137 app.routes holds a wrapper for an included router, not its routes.
        mock_config.get.return_value = "x"
        app = FastAPI()
        inner = APIRouter(prefix="/reports")
        inner.add_api_route("/daily", _endpoint, methods=["GET"], summary="Daily report")
        nested = APIRouter()
        nested.add_api_route("/rebuild", _endpoint, methods=["POST"], summary="Rebuild")
        inner.include_router(nested, prefix="/admin")
        app.include_router(inner, prefix="/api/agent")
        api = RootApi(app=app)
        html = await api.root()
        assert '<a href="/api/agent/reports/daily">/api/agent/reports/daily</a>' in html
        assert "/api/agent/reports/admin/rebuild" in html
        assert "Daily report" in html
        assert "Rebuild" in html

    async def test_route_hidden_from_schema_is_not_listed(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        app = _make_app(routes=[_GET_ROUTE])
        app.add_api_route("/internal", _endpoint, methods=["GET"], include_in_schema=False)
        api = RootApi(app=app)
        html = await api.root()
        assert "/items" in html
        assert "/internal" not in html

    async def test_get_route_renders_direct_href_link(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        api = RootApi(app=_make_app(routes=[_GET_ROUTE]))
        html = await api.root()
        assert '<a href="/items">/items</a>' in html

    async def test_post_route_with_docs_url_renders_swagger_anchor(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        api = RootApi(app=_make_app(docs_url="/docs", routes=[_POST_ROUTE]))
        html = await api.root()
        # /data → replace "/" with "-" → "-data" → strip "-" → "data"
        assert 'href="/docs#data"' in html
        assert 'title="Open in Swagger"' in html

    async def test_post_route_without_docs_url_renders_plain_path(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        api = RootApi(app=_make_app(docs_url=None, routes=[_POST_ROUTE]))
        html = await api.root()
        assert "/data" in html
        assert 'title="Open in Swagger"' not in html

    async def test_route_summary_appears_in_table_row(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        api = RootApi(app=_make_app(routes=[_GET_ROUTE]))
        html = await api.root()
        assert "List items" in html

    # One route serving GET and POST appears twice in the schema, and FastAPI derives both
    # operation IDs from the route's first method only, so it warns that they collide. That is
    # FastAPI's behaviour for any such route (RestApiBase's decorators never declare one), not
    # something this test is about.
    @pytest.mark.filterwarnings("ignore:Duplicate Operation ID")
    async def test_methods_appear_sorted_in_table_row(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        api = RootApi(app=_make_app(routes=[("/multi", ["POST", "GET"], "Multi")]))
        html = await api.root()
        assert "GET, POST" in html  # sorted order

    async def test_two_routes_on_one_path_get_two_rows(self, mock_config: MagicMock, mock_registry: MagicMock) -> None:
        mock_config.get.return_value = "x"
        api = RootApi(app=_make_app(routes=[("/items", ["GET"], "List items"), ("/items", ["POST"], "Create an item")]))
        html = await api.root()
        tbody = html.split("<tbody>")[1].split("</tbody>")[0]
        assert tbody.count("<tr>") == 2
        assert "<td>GET</td>" in tbody
        assert "<td>POST</td>" in tbody


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    async def test_second_call_returns_same_string_object(self, root_api: RootApi) -> None:
        first = await root_api.root()
        second = await root_api.root()
        assert second is first

    async def test_config_not_consulted_on_second_call(self, root_api: RootApi, mock_config: MagicMock) -> None:
        await root_api.root()
        mock_config.get.reset_mock()

        await root_api.root()

        mock_config.get.assert_not_called()
