"""What becomes of a job's partial output when it is given up on (#634): a move's copy part-way, asked about before a
cancel or a clear removes its row.

**The destination is asked first whether it answers**, on a :class:`borco_core.PresenceScan`'s daemon threads and never
on the GUI thread ([[appendices.code-conventions#worker-threads]]): a copy on a share that does not answer cannot be
removed, so it is not offered -- the question says it stays, for the owner to remove by hand. One that answers is
offered both ways, removing it the default: a copy left behind blocks a new move to the same place, though not its own
Retry, which goes on from it.

A cancel hands the choice to the job (:meth:`~rehuco_core.tasks.PartialOutputJob.keep_partial`), which takes the copy
back on its way out or when the queue gives it up; a clear has the job remove it
(:meth:`~rehuco_core.tasks.PartialOutputJob.discard_partial`) before the row goes.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import Final

from borco_core import Presence, PresenceScan
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QWidget
from rehuco_core import FINISHED_JOB_STATES, PartialOutputJob, TaskQueue


class GiveUp(Enum):
    """How the rows are given up on."""

    CANCEL = auto()
    """Cancelled: each job stops, and keeps its copy or takes it back as asked."""

    CLEAR = auto()
    """Removed from the queue: each finished job's copy stays or goes as asked, then the row goes."""


class Choice(Enum):
    """What the owner answered."""

    REMOVE = auto()
    """Go ahead, removing every partial copy that can be removed."""

    KEEP = auto()
    """Go ahead, leaving every partial copy where it is."""

    PROCEED = auto()
    """Go ahead; every partial copy is on a destination that does not answer, so there was nothing to choose."""


VERBS: Final = {GiveUp.CANCEL: "Cancel", GiveUp.CLEAR: "Clear"}
"""What each way of giving up is called on the question's buttons and title."""


@dataclass
class Asking:
    """One question on its way: the rows it is about, and what the scan has said of each partial copy so far.

    :param action: how the rows are given up on.
    :param serials: every row given up on, those with no partial copy included.
    :param partials: each row with a partial copy, by serial: its job and where the copy is.
    :param answers: what the scan said of each copy's place, filled as it answers.
    """

    action: GiveUp
    serials: list[int]
    partials: dict[int, tuple[PartialOutputJob, Path]]
    answers: dict[Path, Presence] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """Whether every copy's place has been answered for."""
        return all(path in self.answers for _, path in self.partials.values())


# one method is the design: a plain object whose stop outlives the Qt side, as StartupPresence's scan's does
# pylint: disable-next=too-few-public-methods
class ScanHolder:
    """The scan of the question on its way, stopped when the question's owner goes -- a plain object, so its ``stop``
    is safe to call from ``destroyed`` once the Qt side is gone."""

    def __init__(self) -> None:
        self.scan: PresenceScan | None = None

    def stop(self) -> None:
        """Stop the scan on its way, if any; it delivers nothing more."""
        if self.scan is not None:
            self.scan.stop()


class PartialCopyQuestion(QObject):
    """Asks, before rows are cancelled or cleared, what becomes of their jobs' partial copies -- then gives them up.

    One question at a time: a second asked while one waits for its scan is dropped.

    :param queue: the queue the rows are in.
    :param parent: the widget the question is shown over.
    """

    __relayed: Signal = Signal(object, object, object)
    """Emitted from a scan thread with each answer and the question it is for; its slot runs on the GUI thread."""

    def __init__(self, queue: TaskQueue, parent: QWidget) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__window: Final = parent
        self.__asking: Asking | None = None
        self.__scans: Final = ScanHolder()
        self.__relayed.connect(self.__on_answer, Qt.ConnectionType.QueuedConnection)
        self.destroyed.connect(self.__scans.stop)

    def ask(self, action: GiveUp, serials: Sequence[int]) -> bool:
        """Take the rows when any has a partial copy: ask about the copies once their places have answered, then give
        every row up as answered.

        :param action: how the rows are given up on.
        :param serials: the rows.
        :returns: whether the rows were taken -- a question was on its way already, or is now; ``False`` when none
            has a partial copy, and the caller gives them up its own way.
        """
        partials = self.__partials(action, serials)
        if not partials:
            return False
        if self.__asking is None:
            asking = Asking(action, list(serials), partials)
            self.__asking = asking
            self.__scans.scan = PresenceScan({path for _, path in partials.values()}, partial(self.__relay, asking))
            self.__scans.scan.start()
        return True

    def __partials(self, action: GiveUp, serials: Sequence[int]) -> dict[int, tuple[PartialOutputJob, Path]]:
        """The rows among ``serials`` whose job has a partial copy this giving up decides on, as last known; reads no
        file. A cancel does nothing to a finished row, so its copy is not asked about.

        :param action: how the rows are given up on.
        :param serials: the rows.
        :returns: each such row's job and where its copy is, by serial.
        """
        untouched = (
            {status.serial for status in self.__queue.jobs() if status.state in FINISHED_JOB_STATES}
            if action is GiveUp.CANCEL
            else set()
        )
        found: dict[int, tuple[PartialOutputJob, Path]] = {}
        for serial in serials:
            if serial in untouched:
                continue
            job = self.__queue.job(serial)
            if isinstance(job, PartialOutputJob) and (path := job.partial) is not None:
                found[serial] = (job, path)
        return found

    def __relay(self, asking: Asking, path: Path, presence: Presence) -> None:
        """The scan's callback, on a scan thread: hand the answer to the GUI thread and nothing else."""
        self.__relayed.emit(asking, path, presence)

    @Slot(object, object, object)
    def __on_answer(self, asking: Asking, path: Path, presence: Presence) -> None:
        """On the GUI thread: note the answer; once every place answered, ask and act.

        :param asking: the question the answer is for -- each place is answered once, so never one already shown.
        :param path: a partial copy's place.
        :param presence: what the scan said of it.
        """
        asking.answers[path] = presence  # pylint: disable=unsupported-assignment-operation
        if not asking.complete:
            return
        self.__asking = None
        self.__scans.scan = None
        away = {serial for serial, (_, place) in asking.partials.items() if asking.answers[place] is Presence.OFFLINE}
        choice = self.__choose(asking, away)
        if choice is not None:
            self.__give_up(asking, away, choice)

    def __choose(self, asking: Asking, away: set[int]) -> Choice | None:
        """Show the question and read the answer.

        :param asking: the question.
        :param away: the rows whose copy's place does not answer.
        :returns: what was chosen, or ``None`` for giving nothing up.
        """
        verb = VERBS[asking.action]
        count = len(asking.serials)
        box = QMessageBox(
            QMessageBox.Icon.Question,
            verb,
            f"{verb} this job?" if count == 1 else f"{verb} {count} jobs?",
            QMessageBox.StandardButton.NoButton,
            self.__window,
        )
        here = [serial for serial in asking.partials if serial not in away]
        lines = [
            f"The partial copy of {job.label} is in {path}."
            if serial in here
            else f"The destination of {job.label} does not answer: its partial copy in {path} stays there, for you to "
            "remove by hand."
            for serial, (job, path) in asking.partials.items()
        ]
        box.setInformativeText("\n\n".join(lines))
        buttons: dict[object, Choice] = {}
        if here:
            copies = "Partial Copy" if len(here) == 1 else "Partial Copies"
            remove = box.addButton(f"Remove {copies}", QMessageBox.ButtonRole.AcceptRole)
            buttons[remove] = Choice.REMOVE
            buttons[box.addButton(f"Keep {copies}", QMessageBox.ButtonRole.AcceptRole)] = Choice.KEEP
            default = remove
        else:
            buttons[box.addButton(verb, QMessageBox.ButtonRole.AcceptRole)] = Choice.PROCEED
            default = None
        refuse = box.addButton(f"Don't {verb}", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(refuse if default is None else default)
        box.setEscapeButton(refuse)
        box.exec()
        choice = buttons.get(box.clickedButton())
        box.deleteLater()
        return choice

    def __give_up(self, asking: Asking, away: set[int], choice: Choice) -> None:
        """Give the rows up as answered.

        :param asking: the question.
        :param away: the rows whose copy's place does not answer: their copies stay, whatever was chosen.
        :param choice: what was chosen.
        """
        if asking.action is GiveUp.CANCEL:
            for serial in asking.serials:
                if serial in asking.partials:
                    asking.partials[serial][0].keep_partial(choice is not Choice.REMOVE or serial in away)
                self.__queue.cancel(serial)
            return
        if choice is Choice.REMOVE:
            for serial, (job, _) in asking.partials.items():
                if serial not in away:
                    job.discard_partial()
        self.__queue.remove(*asking.serials)
