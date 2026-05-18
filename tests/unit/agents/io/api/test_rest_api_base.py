"""Unit tests for RestApiBase."""

from unittest.mock import MagicMock


from blueprint.agents.io.api.rest_api_base import RestApiBase

# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class _MinimalApi(RestApiBase):
    """Minimal concrete subclass — implements required abstract methods."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass


class _RoutedApi(RestApiBase):
    """Concrete subclass with one decorated route per HTTP verb."""

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    @RestApiBase.get("/items")
    async def list_items(self) -> list:
        return []

    @RestApiBase.post("/items")
    async def create_item(self) -> dict:
        return {}

    @RestApiBase.put("/items/{id}")
    async def update_item(self) -> dict:
        return {}

    @RestApiBase.delete("/items/{id}")
    async def delete_item(self) -> None:
        pass

    @RestApiBase.patch("/items/{id}")
    async def patch_item(self) -> dict:
        return {}


# ---------------------------------------------------------------------------
# Route decorator tests
# ---------------------------------------------------------------------------


class TestRouteDecorators:
    def test_get_decorator_attaches_route_attr(self) -> None:
        assert hasattr(_RoutedApi.list_items, "_route")
        verb, path, _ = _RoutedApi.list_items._route
        assert verb == "get"
        assert path == "/items"

    def test_post_decorator_attaches_route_attr(self) -> None:
        verb, path, _ = _RoutedApi.create_item._route
        assert verb == "post"
        assert path == "/items"

    def test_put_decorator_attaches_route_attr(self) -> None:
        verb, path, _ = _RoutedApi.update_item._route
        assert verb == "put"
        assert path == "/items/{id}"

    def test_delete_decorator_attaches_route_attr(self) -> None:
        verb, path, _ = _RoutedApi.delete_item._route
        assert verb == "delete"
        assert path == "/items/{id}"

    def test_patch_decorator_attaches_route_attr(self) -> None:
        verb, path, _ = _RoutedApi.patch_item._route
        assert verb == "patch"
        assert path == "/items/{id}"

    def test_decorator_stores_kwargs(self) -> None:
        @RestApiBase.get("/tagged", tags=["foo"], summary="bar")
        async def tagged_fn(self):
            pass

        _, _, kwargs = tagged_fn._route
        assert kwargs["tags"] == ["foo"]
        assert kwargs["summary"] == "bar"

    def test_undecorated_method_has_no_route_attr(self) -> None:
        assert not hasattr(_MinimalApi.on_startup, "_route")


# ---------------------------------------------------------------------------
# _wire_routes tests
# ---------------------------------------------------------------------------


class TestWireRoutes:
    def test_router_has_routes_after_init(self, mock_config: MagicMock) -> None:
        api = _RoutedApi()
        assert len(api.router.routes) > 0

    def test_all_five_verbs_are_registered(self, mock_config: MagicMock) -> None:
        api = _RoutedApi()
        flat = {m for route in api.router.routes if hasattr(route, "methods") for m in route.methods}
        assert {"GET", "POST", "PUT", "DELETE", "PATCH"}.issubset(flat)

    def test_no_routes_when_no_decorated_methods(self, mock_config: MagicMock) -> None:
        api = _MinimalApi()
        assert len(api.router.routes) == 0

    def test_subclass_routes_are_inherited(self, mock_config: MagicMock) -> None:
        """Routes defined on a parent class must appear on the child router."""

        class _Child(_RoutedApi):
            async def on_startup(self) -> None:
                pass

            async def on_shutdown(self) -> None:
                pass

        child = _Child()
        paths = [route.path for route in child.router.routes if hasattr(route, "path")]
        assert "/items" in paths


# ---------------------------------------------------------------------------
# _build_problem_details tests
# ---------------------------------------------------------------------------


class TestBuildProblemDetails:
    def test_string_detail_stored_under_detail_key(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=404,
            detail="Not found",
            instance="/api/items/1",
            trace_id="abc123",
        )
        assert problem["detail"] == "Not found"

    def test_status_code_stored(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=500,
            detail="Error",
            instance="/path",
            trace_id="t1",
        )
        assert problem["status"] == 500

    def test_instance_stored(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=400,
            detail="Bad",
            instance="/path/to/resource",
            trace_id="t2",
        )
        assert problem["instance"] == "/path/to/resource"

    def test_trace_id_stored(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=422,
            detail="Unprocessable",
            instance="/",
            trace_id="trace-xyz",
        )
        assert problem["traceId"] == "trace-xyz"

    def test_default_type_is_about_blank(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=400,
            detail="err",
            instance="/",
            trace_id="t",
        )
        assert problem["type"] == "about:blank"

    def test_custom_type_uri_overrides_default(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=400,
            detail="err",
            instance="/",
            trace_id="t",
            type_uri="https://example.com/errors/validation",
        )
        assert problem["type"] == "https://example.com/errors/validation"

    def test_title_resolved_from_status_code(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=404,
            detail="err",
            instance="/",
            trace_id="t",
        )
        assert problem["title"] == "Not Found"

    def test_custom_title_overrides_resolved_title(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=404,
            detail="err",
            instance="/",
            trace_id="t",
            title="Custom Title",
        )
        assert problem["title"] == "Custom Title"

    def test_dict_detail_keys_are_preserved(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=503,
            detail={"reason": "overloaded", "errors": ["err1"]},
            instance="/health",
            trace_id="t3",
        )
        assert problem["status"] == 503
        assert problem["errors"] == ["err1"]
        assert problem["reason"] == "overloaded"

    def test_none_detail_becomes_empty_string(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=500,
            detail=None,
            instance="/",
            trace_id="t",
        )
        assert problem["detail"] == ""

    def test_all_required_fields_present(self) -> None:
        problem = RestApiBase._build_problem_details(
            status_code=400,
            detail="bad request",
            instance="/path",
            trace_id="tid",
        )
        for key in ("type", "title", "status", "detail", "instance", "traceId"):
            assert key in problem


# ---------------------------------------------------------------------------
# _resolve_status_title tests
# ---------------------------------------------------------------------------


class TestResolveStatusTitle:
    def test_known_status_code_returns_phrase(self) -> None:
        assert RestApiBase._resolve_status_title(200) == "OK"
        assert RestApiBase._resolve_status_title(404) == "Not Found"
        assert RestApiBase._resolve_status_title(500) == "Internal Server Error"

    def test_unknown_status_code_returns_unknown_error(self) -> None:
        assert RestApiBase._resolve_status_title(999) == "Unknown Error"
