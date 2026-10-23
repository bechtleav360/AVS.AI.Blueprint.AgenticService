"""The CLI's own output encoding.

`asbs` prints check marks, warning signs and box drawing. Python encodes stdout with the locale
encoding, and on Windows that is cp1252, which has none of those characters -- so the first line
of output raised `UnicodeEncodeError`, and it did so *mid-command*: `asbs create handler` died
after writing the handler file and before registering it in `main.py`.

The rule the fix keeps: what the CLI **prints** may be UTF-8, and what it **writes** stays ASCII.
The second half is asserted in `tests/unit/agent_generator/generator/test_generated_project.py`.
"""

import io

import pytest

from blueprint.agent_generator.cli.main import use_utf8


class RefusesEncoding(io.StringIO):
    """A stream that will not change encoding but will change error handling.

    Stands in for a handle Python has already committed to an encoding -- the case the fallback
    exists for, and one that cannot be produced reliably in a test by redirecting anything.
    """

    def __init__(self) -> None:
        super().__init__()
        self.errors_set: str | None = None

    def reconfigure(self, *, encoding: str | None = None, errors: str | None = None) -> None:  # type: ignore[override]
        if encoding is not None:
            raise ValueError("cannot change encoding on this stream")
        self.errors_set = errors


class TakesNothing(io.StringIO):
    """A stream with no ``reconfigure`` at all, which must not be an error."""

    reconfigure = None  # type: ignore[assignment]


class TestTheOutputEncoding:
    def test_a_stream_is_reconfigured_to_utf8(self) -> None:
        stream = io.StringIO()
        stream.reconfigure = lambda **kwargs: setattr(stream, "seen", kwargs)  # type: ignore[attr-defined,method-assign]

        use_utf8(stream)

        assert stream.seen == {"encoding": "utf-8", "errors": "replace"}  # type: ignore[attr-defined]

    def test_a_stream_that_refuses_utf8_still_stops_raising(self) -> None:
        """The fallback: a lost glyph becomes '?' in a log rather than an abandoned command."""
        stream = RefusesEncoding()

        use_utf8(stream)

        assert stream.errors_set == "replace"

    def test_a_stream_without_reconfigure_is_left_alone(self) -> None:
        use_utf8(TakesNothing())  # must not raise

    @pytest.mark.parametrize("glyph", ["\u2713", "\u26a0", "\u251c", "\u2500"])
    def test_the_glyphs_the_cli_prints_survive_the_round_trip(self, glyph: str) -> None:
        """cp1252 has none of these: the check mark, the warning sign and two box-drawing
        characters, which between them are every non-ASCII character the commands print."""
        with pytest.raises(UnicodeEncodeError):
            glyph.encode("cp1252")

        assert glyph.encode("utf-8").decode("utf-8") == glyph
