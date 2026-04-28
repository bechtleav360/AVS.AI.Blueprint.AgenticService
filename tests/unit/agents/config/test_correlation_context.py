"""Unit tests for CorrelationContext and CorrelationContextProvider."""

import logging

import pytest

from blueprint.agents.config.custom_logging import (
    CorrelationContext,
    CorrelationContextProvider,
)


class TestCorrelationContext:
    @pytest.fixture
    def ctx(self) -> CorrelationContext:
        return CorrelationContext()

    def test_default_value_is_na(self, ctx: CorrelationContext) -> None:
        assert ctx.get() == "n/a"

    def test_set_updates_current_value(self, ctx: CorrelationContext) -> None:
        ctx.set("abc-123")
        assert ctx.get() == "abc-123"

    def test_set_returns_token(self, ctx: CorrelationContext) -> None:
        token = ctx.set("some-id")
        assert token is not None

    def test_reset_restores_previous_value(self, ctx: CorrelationContext) -> None:
        # ContextVar.reset(token) reverts to the state that existed *before* the
        # set() call that produced the token — so we capture the token from
        # set("second") to restore back to "first".
        ctx.set("first")
        token = ctx.set("second")
        ctx.reset(token)
        assert ctx.get() == "first"

    def test_reset_none_is_noop(self, ctx: CorrelationContext) -> None:
        ctx.set("stable")
        ctx.reset(None)
        assert ctx.get() == "stable"

    def test_set_none_normalises_to_empty_string(self, ctx: CorrelationContext) -> None:
        ctx.set(None)
        assert ctx.get() == ""

    def test_build_filter_injects_correlation_id_onto_record(self, ctx: CorrelationContext) -> None:
        ctx.set("test-correlation-id")
        filt = ctx.build_filter()
        record = logging.LogRecord(name="test", level=logging.INFO, pathname="", lineno=0, msg="", args=(), exc_info=None)
        result = filt.filter(record)
        assert result is True
        assert record.correlation_id == "test-correlation-id"

    def test_build_filter_reflects_updated_value(self, ctx: CorrelationContext) -> None:
        """The filter always reads the current context value, not the value at build time."""
        filt = ctx.build_filter()
        ctx.set("updated-id")
        record = logging.LogRecord(name="test", level=logging.INFO, pathname="", lineno=0, msg="", args=(), exc_info=None)
        filt.filter(record)
        assert record.correlation_id == "updated-id"

    def test_independent_instances_do_not_share_state(self) -> None:
        ctx_a = CorrelationContext()
        ctx_b = CorrelationContext()
        ctx_a.set("id-a")
        ctx_b.set("id-b")
        assert ctx_a.get() == "id-a"
        assert ctx_b.get() == "id-b"


class TestCorrelationContextProvider:
    def test_returns_same_instance_on_repeated_calls(self) -> None:
        a = CorrelationContextProvider.get_correlation_context()
        b = CorrelationContextProvider.get_correlation_context()
        assert a is b

    def test_returned_instance_is_correlation_context(self) -> None:
        assert isinstance(CorrelationContextProvider.get_correlation_context(), CorrelationContext)
