"""One log record, formatted once and placed, as every log surface consumes it."""

from collections.abc import Hashable
from dataclasses import dataclass
from logging import LogRecord


@dataclass(frozen=True, slots=True)
class LogEntry:
    """A log record with the three things a surface needs that the record itself cannot answer.

    Frozen because it is handed to every sink that wants it and to a model that keeps it for the rest
    of the run: one shared object, never one copy per reader, so nobody may edit it.
    """

    record: LogRecord
    """The record as ``logging`` built it -- level, time, module, line, the unformatted message."""

    message: str
    """The record put through the handler's `logging.Formatter`, **once**, when it arrived.

    Formatting is neither free nor idempotent -- ``record.getMessage()`` interpolates arguments, and a
    formatter can read ``exc_info`` -- so a table that formatted in ``data()`` would re-run it for
    every repaint of every visible row, and a record whose arguments are mutable would render
    differently depending on when it was scrolled into view."""

    scopes: tuple[Hashable, ...]
    """Everything the record is about (:class:`~.log_scope.LogScope`), outermost first -- empty when it
    is about nothing in particular. Resolved when the record arrived, on the thread that logged it,
    because that is the only moment the answer exists.

    A sink is routed this by **membership**, not equality: work on a document, run as a queued job, is
    about both, and each surface is owed the record without the other losing it."""

    serial: int
    """Position in the run, counted from the first record the bridge ever saw and never reused.

    Not a row number: every ring buffer downstream drops its oldest entries, so row 0 is a different
    record over time and the same record has a different row in each surface holding it. The serial is
    what survives that: it is how the bridge knows which entries a sink has already been given, and the
    one number a reader can carry between two surfaces showing the same run."""
