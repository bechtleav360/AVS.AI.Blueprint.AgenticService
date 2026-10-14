"""Find agent code that swallows a cancellation -- what ``nats_handler_timeout`` relies on.

When a run exceeds ``nats_handler_timeout`` the framework cancels it: an
``asyncio.CancelledError`` is raised wherever the run is awaiting. Code that catches it without
re-raising keeps the run going past the limit. The run then still holds its slot, and when it
finally returns the delivery is nak'd and redelivered anyway, because the limit was exceeded -- so
whatever it went on to finish may be done a second time.

Parsed rather than imported, like everything ``asbs validate`` checks.
"""

import ast
from pathlib import Path

CANCELLATION_NAMES = frozenset({"CancelledError", "BaseException"})
"""Exception names whose ``except`` catches a cancellation. ``Exception`` does not (Python 3.8+)."""

SHOWN = 5
"""How many places one warning lists before it summarises the rest."""


def swallowed_cancellations(src_dir: Path) -> list[str]:
    """Return ``"path:line"`` for every place under ``src_dir`` that catches a cancellation and does not re-raise.

    Reported: a bare ``except:``, ``except BaseException``, ``except (asyncio.)CancelledError`` -- alone
    or in a tuple -- whose body contains no ``raise``, and ``contextlib.suppress(...)`` naming one of
    them. A handler that re-raises (``except asyncio.CancelledError: ...; raise``) is fine.
    """
    found: list[str] = []
    root = src_dir.parent
    for path in sorted(src_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue  # not this check's to report
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _catches_cancellation(node.type) and not _reraises(node):
                found.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
            elif isinstance(node, ast.With | ast.AsyncWith):
                for item in node.items:
                    if _suppresses_cancellation(item.context_expr):
                        found.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
    return found


def swallowed_cancellation_warning(agent: str, found: list[str]) -> str:
    """The warning for ``found``, naming the agent and what follows from it."""
    shown = ", ".join(found[:SHOWN])
    more = f" and {len(found) - SHOWN} more" if len(found) > SHOWN else ""
    return (
        f"Agent '{agent}' catches asyncio.CancelledError without re-raising it ({shown}{more}). When a run exceeds "
        "'nats_handler_timeout' it is cancelled; code that swallows the cancellation keeps working past the limit, "
        "holding its slot, and when it returns the delivery is nak'd and redelivered anyway -- so what it finished may "
        "run twice. Re-raise it ('except asyncio.CancelledError: raise' before a broader handler), or catch 'Exception', "
        "which does not include it."
    )


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _catches_cancellation(caught: ast.expr | None) -> bool:
    if caught is None:
        return True  # bare except
    if isinstance(caught, ast.Tuple):
        return any(_name(element) in CANCELLATION_NAMES for element in caught.elts)
    return _name(caught) in CANCELLATION_NAMES


def _reraises(handler: ast.ExceptHandler) -> bool:
    """Whether the handler raises anything, not counting functions defined inside it."""
    stack: list[ast.AST] = list(handler.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return False


def _suppresses_cancellation(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Call)
        and _name(expr.func) == "suppress"
        and any(_name(argument) in CANCELLATION_NAMES for argument in expr.args)
    )
