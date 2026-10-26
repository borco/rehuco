"""What is holding a refused rename, and what to do about it (#505): the banner magnifier's dialog.

Modelled on PowerToys File Locksmith: the programs that have the resource's files open, each with
**Show App** -- its window brought to the front, to close the file there -- and **End Task**, which ends it
the way Task Manager does. Ending is slow by the operating system's clock and asking is slow by the share's,
so both run on the pool and land back here; a program that ended leaves the list, and one that could not be
ended gets its button back with the reason said below.

Asked when the dialog opens and again on **Refresh**, never by the rename itself: the question lists the
resource's files and registers them with the Restart Manager, which only someone who clicked should wait for.
"""

import logging
from pathlib import Path
from typing import Final, cast

from borco_core import end_process, has_window, show_window
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QDialog, QWidget
from rehuco_core import is_directory_scoped

from ..documents.rename_holders import HoldersFound, RenameHolderReport
from .holder_row import HolderRow
from .rename_holders_dialog_ui import Ui_RenameHoldersDialog

LOG: Final = logging.getLogger(__name__)

END_TIMEOUT: Final = 5.0
"""How long *End Task* waits for a program to exit, in seconds. A terminated process is gone in milliseconds;
one that is not by then is stuck in the kernel -- a driver call, a dead share -- and waiting longer will not end
it."""

INTRO: Final = "Programs that have the files of “{name}” open:"
SEARCHING: Final = "Looking for programs that have its files open…"
COULD_NOT_ASK: Final = "Could not ask Windows who has its files open: {reason}"
COULD_NOT_SHOW: Final = "{name} has no window to show any more."
NOT_ENDED: Final = "{name} was not ended: {reason}"
STILL_RUNNING: Final = "{name} is still running {seconds:.0f} seconds after it was told to end."


class HoldersSignals(QObject):
    """The sender one pool job answers through, deleted on the GUI thread only -- the shape
    :class:`~rehuco_agent.rehuco.roots_lightbox.ListingSignals` has, so an answer that lands after the dialog
    closed reaches nobody.

    :param pool: the pool the job runs on, which owns the sender.
    """

    found = Signal(int, object, str)
    """``(generation, found, failure)``: who holds the files, or ``None`` and why the question failed."""

    ended = Signal(int, bool, str)
    """``(pid, gone, failure)``: whether the program has gone, and why not when it could not be ended."""

    def __init__(self, pool: QThreadPool) -> None:
        super().__init__(pool)


class FindJob(QRunnable):
    """Asks who holds a resource's files, off the GUI thread.

    :param signals: the sender to answer through, already wired; released when the job is done.
    :param generation: which request this answers.
    :param record_path: the resource's ``.rehu``.
    """

    def __init__(self, signals: HoldersSignals, generation: int, record_path: Path) -> None:
        super().__init__()
        self.__signals: Final = signals
        self.__generation: Final = generation
        self.__record_path: Final = record_path

    def run(self) -> None:
        try:
            try:
                found: HoldersFound | None = RenameHolderReport.find(self.__record_path)
                failure = ""
            except Exception as error:  # pylint: disable=broad-exception-caught
                # the pool would swallow it and no answer would ever arrive: the dialog is told why instead
                LOG.exception("Asking who holds the files of %s failed", self.__record_path)
                found, failure = None, str(error)
            self.__signals.found.emit(self.__generation, found, failure)
        finally:
            self.__signals.deleteLater()


class EndJob(QRunnable):
    """Ends one program and waits for it to go, off the GUI thread.

    :param signals: the sender to answer through, already wired; released when the job is done.
    :param pid: the program's process id.
    """

    def __init__(self, signals: HoldersSignals, pid: int) -> None:
        super().__init__()
        self.__signals: Final = signals
        self.__pid: Final = pid

    def run(self) -> None:
        try:
            try:
                gone = end_process(self.__pid, END_TIMEOUT)
                failure = ""
            except OSError as error:
                # access denied, for an elevated program or another user's: said in the operating system's words
                LOG.warning("Ending process %d was refused", self.__pid, exc_info=True)
                gone, failure = False, error.strerror or str(error)
            except Exception as error:  # pylint: disable=broad-exception-caught
                # the pool would swallow it and the button would stay disabled: the dialog is told why instead
                LOG.exception("Ending process %d failed", self.__pid)
                gone, failure = False, str(error)
            self.__signals.ended.emit(self.__pid, gone, failure)
        finally:
            self.__signals.deleteLater()


class RenameHoldersDialog(QDialog):
    """Lists the programs holding a refused rename's files, with *Show App* and *End Task* on each (#505).

    Opened by the banner's magnifier, with :meth:`~PySide6.QtWidgets.QDialog.open`; asks at once.

    :param record_path: the resource's ``.rehu``, where it was when the rename was refused.
    :param parent: optional Qt parent.
    """

    def __init__(self, record_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__record_path: Final = record_path
        self.__ui: Final = Ui_RenameHoldersDialog()
        self.__ui.setupUi(self)
        name = record_path.parent.name if is_directory_scoped(record_path) else record_path.stem
        self.__ui.intro_label.setText(INTRO.format(name=name))
        self.__generation = 0
        self.__found: HoldersFound | None = None
        self.__rows: dict[int, HolderRow] = {}
        self.__ui.refresh_button.clicked.connect(self.refresh)
        self.__ui.close_button.clicked.connect(self.accept)
        self.refresh()

    @property
    def rows(self) -> tuple[HolderRow, ...]:
        """The programs listed, in the order the operating system named them."""
        return tuple(self.__rows.values())

    @property
    def status(self) -> str:
        """What the line under the list says."""
        return self.__ui.status_label.text()

    def refresh(self) -> None:
        """Ask again who holds the files; the list empties until the answer lands, and an answer to an earlier ask
        is dropped."""
        self.__generation += 1
        self.__clear_rows()
        self.__found = None
        self.__ui.status_label.setText(SEARCHING)
        self.__ui.refresh_button.setEnabled(False)
        pool = QThreadPool.globalInstance()
        signals = HoldersSignals(pool)
        signals.found.connect(self.__on_found)
        job = FindJob(signals, self.__generation, self.__record_path)
        job.setAutoDelete(True)
        pool.start(job)

    @Slot(int, object, str)
    def __on_found(self, generation: int, found: HoldersFound | None, failure: str) -> None:
        """List who holds the files, unless a newer ask has gone out since.

        :param generation: which ask this answers.
        :param found: who holds them, or ``None`` when the question failed.
        :param failure: why it failed.
        """
        if generation != self.__generation:
            return
        self.__ui.refresh_button.setEnabled(True)
        if found is None:
            self.__ui.status_label.setText(COULD_NOT_ASK.format(reason=failure))
            return
        self.__found = found
        layout = self.__ui.holders_layout
        rows: dict[int, HolderRow] = {}
        for holder in found.others:
            row = HolderRow(holder, has_window(holder.pid), self.__ui.holders_container)
            row.show_requested.connect(self.__on_show_requested)
            row.end_requested.connect(self.__on_end_requested)
            # before the trailing spacer, which keeps the rows at the top
            layout.insertWidget(layout.count() - 1, row)
            rows[holder.pid] = row
        # built locally and rebound: pylint reads an item assignment on a dict attribute as one on a signal
        self.__rows = rows
        self.__update_status()

    def __on_show_requested(self, pid: int) -> None:
        """Bring a holder's window to the front, or say it has none any more.

        :param pid: the holder's process id.
        """
        if not show_window(pid):
            self.__ui.status_label.setText(COULD_NOT_SHOW.format(name=self.__rows[pid].holder.name))

    def __on_end_requested(self, pid: int) -> None:
        """End a holder, its *End Task* disabled until the answer lands.

        :param pid: the holder's process id.
        """
        self.__rows[pid].set_ending(True)
        pool = QThreadPool.globalInstance()
        signals = HoldersSignals(pool)
        signals.ended.connect(self.__on_ended)
        job = EndJob(signals, pid)
        job.setAutoDelete(True)
        pool.start(job)

    @Slot(int, bool, str)
    def __on_ended(self, pid: int, gone: bool, failure: str) -> None:
        """Take an ended holder off the list, or give a surviving one its button back and say why.

        :param pid: the holder's process id.
        :param gone: whether it has gone.
        :param failure: why it could not be ended, or empty when it was told to and outlived the wait.
        """
        row = self.__rows.get(pid)
        if row is None:
            return
        if gone:
            self.__rows = {other: kept for other, kept in self.__rows.items() if other != pid}
            self.__remove_row(row)
            self.__update_status()
            return
        row.set_ending(False)
        name = row.holder.name
        self.__ui.status_label.setText(
            NOT_ENDED.format(name=name, reason=failure)
            if failure
            else STILL_RUNNING.format(name=name, seconds=END_TIMEOUT)
        )

    def __update_status(self) -> None:
        """Say what the list does not: whether this process is in the way, or that nobody is."""
        # set by the answer the rows were listed from, and cleared with them by a refresh
        found = cast(HoldersFound, self.__found)
        self.__ui.status_label.setText(found.notes(len(self.__rows)))

    def __clear_rows(self) -> None:
        """Take every holder off the list."""
        for row in self.__rows.values():
            self.__remove_row(row)
        self.__rows = {}

    def __remove_row(self, row: HolderRow) -> None:
        """Take one row out of the list and delete it.

        :param row: the row.
        """
        self.__ui.holders_layout.removeWidget(row)
        # hidden now: deleted only once control is back in the event loop, and it would sit over the rows until then
        row.hide()
        row.deleteLater()
