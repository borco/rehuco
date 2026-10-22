"""Records read for the open documents off the GUI thread, so a share that has gone silent never holds the window (#564,
[[offline-editing#overview]])."""

import logging
import threading
from collections.abc import Callable
from itertools import count
from typing import Final

from borco_core.logging import LogScope
from PySide6.QtCore import QObject, Qt, Signal
from rehuco_core import DEFAULT_RENAME_COORDINATOR, RehuDocument, RenameCoordinator
from rehuco_core.access import LoadedRecord, Records, ResourceKey

from ..settings.identity_settings import shared_identity_settings

LOG: Final = logging.getLogger(__name__)


class RecordReader(QObject):
    """Reads one record at a time per request, on a daemon thread, and answers on the GUI thread.

    **A read runs on a daemon thread** ([[appendices.code-conventions#worker-threads]]): a share can block a read for
    its whole timeout, and nothing may hold up quitting for it. The read is held under the rename barrier, as every
    off-GUI read of a record is, so a rename never moves the file under it. What it read arrives at the requester's
    callback on the GUI thread; nothing arrives after :meth:`stop`.

    **Whether an answer still matters is the requester's to judge**: a document that moved on to another read, or was
    let go, drops what arrives for a read it no longer waits for.

    :param records: what the records are read through.
    :param coordinator: the rename barrier the reads hold; the app's default when ``None``.
    :param parent: optional Qt parent.
    """

    __answered: Signal = Signal(int, object)
    """Emitted from a read's thread with its ticket and the record; its slot runs on the GUI thread (the connection is
    queued because the sender's thread is not the receiver's)."""

    def __init__(
        self, records: Records, coordinator: RenameCoordinator | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.__records: Final = records
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__tickets: Final = count()
        self.__waiting: Final[dict[int, Callable[[LoadedRecord], None]]] = {}
        """Each read still out, by ticket: who hears its answer."""
        self.__stopped: Final = threading.Event()
        self.__answered.connect(self.__on_answered, Qt.ConnectionType.QueuedConnection)

    def read(self, key: ResourceKey, answer: Callable[[LoadedRecord], None]) -> None:
        """Read ``key`` on a daemon thread and hand the record to ``answer`` on the GUI thread -- or an empty locked
        stub standing in for it when it cannot be read ([[data-model#write-integrity]]).

        The identity it is read under is the one set now (:func:`shared_identity_settings`, #109), read here, on the GUI
        thread: a ``.rehu`` is opened under the **current** user, a ``.tc`` import files its per-user flags under the
        **unknown** one.

        :param key: the record (a ``.rehu``, or a legacy ``.tc``).
        :param answer: what to do with the record; never called after :meth:`stop`.
        """
        if self.__stopped.is_set():
            return
        ticket = next(self.__tickets)
        self.__waiting[ticket] = answer  # pylint: disable=unsupported-assignment-operation
        threading.Thread(
            target=self.__run, args=(ticket, key, *RecordReader.identity()), name="record-read", daemon=True
        ).start()

    def stop(self) -> None:
        """Answer no read still out, before the window goes."""
        self.__stopped.set()
        self.__waiting.clear()

    @staticmethod
    def identity() -> tuple[str, str]:
        """The identity a record is read under now: the **current** user a ``.rehu`` is opened as, and the **unknown**
        one a ``.tc``'s per-user flags are filed under (#109). Read on the GUI thread, where the settings live.

        :returns: the current and the unknown username.
        """
        settings = shared_identity_settings()
        return settings.current_username, settings.unknown_username

    @staticmethod
    def read_record(records: Records, key: ResourceKey, *, username: str, unknown_username: str) -> LoadedRecord:
        """Read ``key``, or an empty locked stub standing in for it, logged under the resource's own scope (#200) -- the
        one way a record is read for a document, on whichever thread reads it.

        :param records: what the record is read through ([[nodes#access-seam]]), which routes a ``.tc`` to its own
            loader and logs a read that fails, as an error: there is no document -- the stub stands in for one.
        :param key: the record.
        :param username: the identity a ``.rehu`` is opened as.
        :param unknown_username: the identity a ``.tc``'s per-user flags are filed under.
        :returns: the record, or a locked stub standing in for it.
        """
        with LogScope.open(key.path):
            record = records.load(key, username=username, unknown_username=unknown_username)
            if not record.document.load_failed:
                LOG.info("Read %s as %s", key, record.document.type or "an untyped resource")
            return record

    def __run(self, ticket: int, key: ResourceKey, username: str, unknown_username: str) -> None:
        """Read the record under the rename hold and deliver it unless stopped (a daemon thread).

        :param ticket: the read.
        :param key: the record.
        :param username: the identity a ``.rehu`` is opened as.
        :param unknown_username: the identity a ``.tc``'s per-user flags are filed under.
        """
        try:
            with self.__coordinator.holding():
                record = RecordReader.read_record(
                    self.__records, key, username=username, unknown_username=unknown_username
                )
        # a read that raised would otherwise answer nothing, leaving its document waiting for good (#480): it is
        # answered as a file that could not be read, which is what it is
        except Exception as error:  # pylint: disable=broad-exception-caught
            LOG.exception("Could not read %s", key.path)
            document = RehuDocument.locked_stub_for_error(key.path, error, username=username)
            record = LoadedRecord(document, None, tuple(document.lock_reasons), None)
        if self.__stopped.is_set():
            return
        try:
            self.__answered.emit(ticket, record)
        except RuntimeError:  # the reader was destroyed while the read was out
            pass

    def __on_answered(self, ticket: int, record: LoadedRecord) -> None:
        """Hand a read's record to whoever asked for it (GUI thread) -- unless the reader stopped after the record was
        posted, which let go of who asked.

        :param ticket: the read.
        :param record: what it read.
        """
        answer = self.__waiting.pop(ticket, None)
        if answer is not None:
            answer(record)
