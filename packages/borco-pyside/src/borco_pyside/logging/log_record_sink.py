"""What a log surface offers the bridge, so the bridge never has to know it is a widget."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .log_entry import LogEntry


@runtime_checkable
class LogRecordSink(Protocol):  # pylint: disable=too-few-public-methods
    """Somewhere log entries can be put -- a table model, a file writer, a test's list.

    One method, deliberately: everything else a log surface does (filtering, clearing, painting,
    scrolling) is its own business and none of the bridge's. In particular there is **no** ``cleared``
    signal for the bridge to listen to -- several surfaces hold their own independent history at once,
    so one of them being emptied says nothing about what the others, or the bridge, should still hold.

    Satisfied structurally: a `QAbstractTableModel` cannot inherit a `Protocol` (mixing its metaclass
    with Shiboken's raises a metaclass conflict), and the bridge only ever calls the method anyway.
    """

    def handle_log_records(self, entries: Sequence[LogEntry]) -> None:
        """Take a batch of entries, oldest first.

        **A batch, not a record**, because the bridge is the only place that can usefully batch: it
        sits on the thread boundary, so every record that arrived while the GUI thread was busy is
        already in its hand at once. A job logging per file over a large tree emits thousands of
        records a second, and a per-record contract would make that thousands of round trips and
        thousands of ``beginInsertRows`` -- which is the UI locking up, not a slow UI.

        Called on the GUI thread, whatever thread the records were logged on. May be called with an
        empty sequence only if the sink asks for entries that do not exist; the bridge never does.

        :param entries: the entries to take, in the order they were logged.
        """
