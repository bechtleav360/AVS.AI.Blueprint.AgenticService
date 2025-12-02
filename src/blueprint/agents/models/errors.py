class HandlerError(Exception):
    """Domain-specific exception raised by handlers."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.code = code or "handler_error"


class RetryableHandlerError(HandlerError):
    """Domain-specific exception raised by handlers that should trigger a retry."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(status=status, reason=reason, code=code)


class CriticalHandlerError(HandlerError):
    """Domain-specific exception raised by handlers that force a restart."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(status=status, reason=reason, code=code)


class InvalidEventError(HandlerError):
    """Domain-specific exception raised by handlers that force a drop of the event."""

    def __init__(self, *, status: str, reason: str, code: str | None = None):
        super().__init__(status=status, reason=reason, code=code)
