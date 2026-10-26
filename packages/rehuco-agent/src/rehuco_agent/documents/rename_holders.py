"""Who is in the way of a refused rename (#355, #505): what the holders dialog lists.

Windows refuses a rename over an open handle with "Access is denied" or "being used by another
process", and says nothing about whose handle it is. The user then has nothing to act on, and the
likeliest holders are ones they can deal with once named: an Explorer window showing the folder, a
shell standing in it, a viewer with an image open, a scanner that will be done in a moment. So a refusal
of that kind lets the user ask the operating system who holds the resource's files
(:func:`borco_core.file_holders`) and, for a folder, who holds the folder itself or anything in it
(:func:`borco_core.folder_holders`) -- a shell's working directory is a handle on the folder, which the
first question cannot see.

**Asked on demand, never on the rename's path** (#505): the questions list the resource's files over
a share too, and walk every handle on the system -- a couple of seconds -- so the banner only reports the
refusal (:meth:`RenameHolderReport.is_lock_refusal`) and offers a button; the dialog it opens asks here, on
a pool thread.
"""

import logging
import os
from itertools import islice
from pathlib import Path
from typing import Final, NamedTuple

from borco_core import FileHolder, file_holders, folder_holders
from rehuco_core import TRANSIENT_LOCK_ERRORS, is_directory_scoped

LOG: Final = logging.getLogger(__name__)

HOLDER_FILE_LIMIT: Final = 512
"""How many of a resource's files are asked about. A pack of loose images can hold thousands, and the
first few hundred found are plenty to catch whoever holds one."""

HELD_BY_REHUCO: Final = (
    "Rehuco itself still has one of its files open. That is a bug in Rehuco: please report it, with the log."
)
"""What the dialog adds when this process is a holder -- a handle the rename barrier should have closed. The app
must never stand in the way of its own rename, so this is said as the bug it is, and logged as an error
(:meth:`RenameHolderReport.find`) so the trace outlives the dialog."""

HELD_BY_OWN_DIRECTORY: Final = (
    "Rehuco's own working directory is inside it. That is a bug in Rehuco: please report it, with the log."
)
"""What the dialog adds when this process is standing in the folder being renamed -- a handle the rename
should have stepped out of (:class:`~rehuco_core.RenameCoordinator`), so reachable only when that failed; said
and logged as a bug, like :data:`HELD_BY_REHUCO`."""

HELD_BY_NOBODY: Final = "No program Rehuco can see has its files open."
"""What the dialog says for a file-scoped resource when nobody holds it -- or nobody does any more."""

FOLDER_HELD_BY_NOBODY: Final = (
    f"{HELD_BY_NOBODY} If an Explorer window is showing the folder, move that window to the parent folder and "
    "try again."
)
"""What the dialog says for a directory-scoped resource when nobody holds it: the operating system
cannot be asked about a handle on the folder itself, and an Explorer window showing it is the one holder
a user can most often do something about -- observed to clear the refusal by itself."""


class HoldersFound(NamedTuple):
    """Who holds a resource's files, as :meth:`RenameHolderReport.find` found them.

    :param others: the other programs holding them, each once, in the order the operating system listed them.
    :param held_by_rehuco: whether this process holds one too.
    :param standing_inside: whether this process's working directory is in the folder being renamed.
    :param directory_scoped: whether the rename was of a folder.
    """

    others: tuple[FileHolder, ...]
    held_by_rehuco: bool
    standing_inside: bool
    directory_scoped: bool

    def notes(self, remaining: int) -> str:
        """What to say beside the list of other programs.

        :param remaining: how many of :attr:`others` are still listed -- the ones not ended since.
        :returns: the sentences about this process, or about nobody holding the files once no other program
            is listed and this process is not in the way either; empty while only other programs are.
        """
        parts: list[str] = []
        if self.held_by_rehuco:
            parts.append(HELD_BY_REHUCO)
        if self.standing_inside:
            parts.append(HELD_BY_OWN_DIRECTORY)
        if not parts and not remaining:
            parts.append(FOLDER_HELD_BY_NOBODY if self.directory_scoped else HELD_BY_NOBODY)
        return " ".join(parts)


class RenameHolderReport:
    """Turns a refused rename into who is holding the resource (#355).

    A namespace for the two questions -- every method is static: whether a failure is a refusal over an open
    handle, and who holds the files.
    """

    @staticmethod
    def is_lock_refusal(error: BaseException) -> bool:
        """Whether ``error``, or the failure it was raised from, is Windows refusing over a handle.

        :param error: why the rename failed -- a :class:`~rehuco_core.PartialRenameError` is looked through to
            the refusal that started it.
        :returns: whether someone holding a file is the likely reason.
        """
        return any(
            isinstance(candidate, OSError) and getattr(candidate, "winerror", None) in TRANSIENT_LOCK_ERRORS
            for candidate in (error, error.__cause__)
        )

    @staticmethod
    def find(record_path: Path) -> HoldersFound:
        """Ask who holds the resource's files -- and, for a folder, the folder itself. Slow, so off the GUI thread.

        A program both questions find is listed once, under the Restart Manager's name for it (*Windows Explorer*
        rather than *explorer.exe*).

        :param record_path: the resource's ``.rehu`` file, where it was before the refused rename.
        :returns: who holds them.
        :raises OSError: the files could not be listed, or the operating system refused a question.
        """
        directory_scoped = is_directory_scoped(record_path)
        holders = file_holders(RenameHolderReport.__resource_files(record_path))
        if directory_scoped:
            known = {holder.pid for holder in holders}
            holders += tuple(holder for holder in folder_holders(record_path.parent) if holder.pid not in known)
        own = os.getpid()
        found = HoldersFound(
            others=tuple(holder for holder in holders if holder.pid != own),
            held_by_rehuco=any(holder.pid == own for holder in holders),
            standing_inside=directory_scoped and RenameHolderReport.__is_working_directory_inside(record_path.parent),
            directory_scoped=directory_scoped,
        )
        # the app in its own way is a bug -- the barrier closes its handles and steps out of the folder before a
        # rename -- so it is logged where it is found: the dialog saying so is closed a moment later
        if found.held_by_rehuco:
            LOG.error(
                "Rehuco holds a file of %s open against its own rename; a reader is outside the barrier.", record_path
            )
        if found.standing_inside:
            LOG.error(
                "Rehuco's working directory is inside %s against its own rename; stepping out failed.",
                record_path.parent,
            )
        return found

    @staticmethod
    def __is_working_directory_inside(directory: Path) -> bool:
        """Whether this process's working directory is ``directory`` or beneath it.

        :param directory: the folder being renamed.
        :returns: whether the process is standing in it; a working directory that cannot be read (it
            was deleted under the process) is not.
        """
        try:
            return Path.cwd().is_relative_to(directory)
        except OSError:
            return False

    @staticmethod
    def __resource_files(record_path: Path) -> list[Path]:
        """The files a rename of the resource moves, up to :data:`HOLDER_FILE_LIMIT`.

        Everything under the folder for a directory-scoped resource; the files named after the record
        for a file-scoped one -- by prefix, which may take in a coincidental neighbour, harmless for a
        question about who holds what.

        :param record_path: the resource's ``.rehu`` file.
        :returns: the files.
        :raises OSError: the folder could not be listed.
        """
        directory = record_path.parent
        if is_directory_scoped(record_path):
            candidates = directory.rglob("*")
        else:
            candidates = (path for path in directory.iterdir() if path.name.startswith(record_path.stem))
        return list(islice((path for path in candidates if path.is_file()), HOLDER_FILE_LIMIT))
