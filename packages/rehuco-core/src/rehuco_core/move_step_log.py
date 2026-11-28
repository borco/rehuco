"""What a record's move says in the log as each of its steps ends (#713).

Split from :mod:`~rehuco_core.move_record_job`, whose module is at pylint's line cap. One INFO line a step, led by the
move's label, with the step's count and its place -- counts only, never a line per file, so a tutorial of two hundred
videos costs the log four lines a move. The Tasks dock's log and a document's show them as the app's log does
([[appendices.logging#what-is-logged]]).
"""

import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Final

from .checksum_reporting import checksum_report_summary
from .move_phases import MoveMode, MovePhase
from .rehu_checksums import ChecksumReport
from .resource_scoping import is_directory_scoped
from .verified_copy import CopyJournal, CopyTally, LeftoversRemoved, name_list

SIZE_UNITS: Final = ("bytes", "KiB", "MiB", "GiB", "TiB")
"""What :func:`size_text` counts in, each a thousand and twenty-four of the one before."""


def counted(count: int, noun: str) -> str:
    """A count and its noun, the noun made plural by an ``s``.

    :param count: how many.
    :param noun: what, in the singular.
    :returns: for example ``1 file`` or ``3 files``.
    """
    return f"{count} {noun}{'' if count == 1 else 's'}"


def size_text(size: int) -> str:
    """A size in bytes, in the largest unit that keeps it above one.

    :param size: the size, in bytes.
    :returns: for example ``512 bytes`` or ``3.4 GiB``.
    """
    value = float(size)
    for unit in SIZE_UNITS[:-1]:
        if value < 1024:
            return f"{size} bytes" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} {SIZE_UNITS[-1]}"


class MoveStepLog:
    """The lines one move writes as its steps end.

    :param log: the logger the move's own lines go through.
    :param label: the move's label, asked at each line since a restored move derives it afresh.
    """

    def __init__(self, log: logging.Logger, label: Callable[[], str]) -> None:
        self.__log: Final = log
        self.__label: Final = label

    def resumed(self, phase: MovePhase, journal: CopyJournal) -> None:
        """Say a run goes on from where an earlier one stopped; a move starting afresh says nothing.

        :param phase: the phase the run starts in.
        :param journal: what a copy wrote so far.
        """
        if phase is not MovePhase.SOURCE:
            self.__say(f"going on from its {phase.value} phase")
        elif journal.written:
            self.__say(
                f"starting over with {counted(len(journal.written), 'file')} of an earlier copy kept, each "
                "checked again"
            )

    def canceled(self, canceled: bool, kept: Path | None) -> None:
        """Say a run ended canceled, and where its copy stays when it was asked to be kept.

        :param canceled: whether a cancel was asked; nothing is said otherwise.
        :param kept: where the copy kept is, or ``None`` for none.
        """
        if canceled:
            self.__say("canceled" if kept is None else f"canceled; the copy in {kept} was kept")

    def verified(self, report: ChecksumReport, when: str, mode: MoveMode) -> None:
        """Say a verify ended: how many files it covered and what it found.

        :param report: what the check established.
        :param when: ``before`` or ``after``.
        :param mode: the move's, which names what the check is before or after.
        """
        step = "copying" if mode is MoveMode.COPY else "renaming"
        self.__say(
            f"verified the checksums of {counted(len(report.statuses), 'file')} {when} {step}: "
            f"{checksum_report_summary(report)}"
        )

    def copied(self, tally: CopyTally, destination: Path) -> None:
        """Say the files were copied: what this run wrote, and apart what an earlier run had.

        :param tally: what the copy did.
        :param destination: the folder the record's own entry landed in.
        """
        earlier = f"; {counted(tally.already, 'file')} already there from an earlier run" if tally.already else ""
        self.__say(f"copied {counted(tally.written, 'file')} ({size_text(tally.size)}) to {destination}{earlier}")

    def compared(self, names: Iterable[str]) -> None:
        """Say which files no checksum covers were compared with their copies, byte for byte.

        :param names: their names; nothing is said for none.
        """
        names = list(names)
        if names:
            self.__say(f"compared {counted(len(names), 'file')} no checksum covers, byte for byte: {name_list(names)}")

    def renamed(self, record: Path, destination: Path, new_name: str) -> None:
        """Say a rename was done, from where to where.

        :param record: the record's ``.rehu`` before the rename.
        :param destination: the folder the record's own entry landed in.
        :param new_name: its name there.
        """
        folder = is_directory_scoped(record)
        landed = destination / new_name if folder else destination / (new_name + record.suffix)
        self.__say(f"renamed {record.parent if folder else record} to {landed}")

    def removed(self, removal: LeftoversRemoved, left: str) -> None:
        """Say what the cleanup removed of the original, and how many items stayed.

        :param removal: what it did.
        :param left: the folder the record's own entry was in.
        """
        stayed = f"; {counted(len(removal.left), 'item')} could not be removed" if removal.left else ""
        self.__say(
            f"removed {counted(removal.files, 'file')} and {counted(removal.folders, 'folder')} from {left}{stayed}"
        )

    def took_back(self, journal: CopyJournal, destination: Path, stayed: int) -> None:
        """Say a canceled or refused copy was taken back.

        :param journal: what the copy wrote and made.
        :param destination: the folder the record's own entry was to land in.
        :param stayed: how many items could not be removed.
        """
        rest = f"; {counted(stayed, 'item')} could not be removed" if stayed else ""
        self.__say(
            f"took back the copy: {counted(len(journal.written), 'file')} and {counted(len(journal.made), 'folder')} "
            f"of it from {destination}{rest}"
        )

    def __say(self, text: str) -> None:
        """Write one line.

        :param text: what the step did.
        """
        self.__log.info("%s: %s", self.__label(), text)
