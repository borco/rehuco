"""Who is in the way of a refused rename (#355): the sentence a rename's error banner ends with.

Windows refuses a rename over an open handle with "Access is denied" or "being used by another
process", and says nothing about whose handle it is. The user then has nothing to act on, and the
likeliest holders are ones they can deal with once named: an Explorer window showing the folder, a
viewer with an image open, a scanner that will be done in a moment. So a refusal of that kind asks the
operating system who holds the resource's files (:func:`borco_core.file_holders`) and says so.
"""

import os
from itertools import islice
from pathlib import Path
from typing import Final

from borco_core import FileHolder, file_holders
from rehuco_core import TRANSIENT_LOCK_ERRORS, is_directory_scoped

HOLDER_FILE_LIMIT: Final = 512
"""How many of a resource's files are asked about. A pack of loose images can hold thousands, and the
first few hundred found are plenty to catch whoever holds one; the question runs on the GUI thread, after
a refusal only, so it is kept short."""

HELD_BY_OTHERS: Final = "It is open in {names}."
"""What the banner adds when other programs hold the resource's files; ``{names}`` lists them."""

HELD_BY_REHUCO: Final = "Rehuco itself still has one of its files open."
"""What the banner adds when this process is a holder -- a handle the rename barrier should have closed,
so worth saying plainly rather than blaming someone else."""

HELD_BY_OWN_DIRECTORY: Final = "Rehuco's own working directory is inside it."
"""What the banner adds when this process is standing in the folder being renamed -- a handle the rename
should have stepped out of (:class:`~rehuco_core.RenameCoordinator`), so reachable only when that failed,
and then worth saying rather than blaming someone else."""

HELD_BY_NOBODY: Final = "No program Rehuco can see has its files open."
"""What the banner adds for a file-scoped resource when the question names nobody."""

FOLDER_HELD_BY_NOBODY: Final = (
    f"{HELD_BY_NOBODY} If an Explorer window is showing the folder, move that window to the parent folder and "
    "try again."
)
"""What the banner adds for a directory-scoped resource when the question names nobody: the operating
system cannot be asked about a handle on the folder itself, and an Explorer window showing it is the one
holder a user can most often do something about -- observed to clear the refusal by itself."""


class RenameHolderReport:  # pylint: disable=too-few-public-methods
    """Turns a refused rename into who is holding the resource (#355).

    A namespace for the one question -- every method is static, and :meth:`describe` is the whole
    public surface.
    """

    @staticmethod
    def describe(record_path: Path, error: BaseException) -> str:
        """The sentence naming who holds the resource, for a rename refused over an open handle.

        :param record_path: the resource's ``.rehu`` file, where it was before the rename.
        :param error: why the rename failed -- a :class:`~rehuco_core.PartialRenameError` is looked
            through to the refusal that started it.
        :returns: one or two sentences, or an empty string when the failure was not a refusal of that
            kind, or when the question could not be asked.
        """
        if not RenameHolderReport.__is_lock_refusal(error):
            return ""
        try:
            holders = file_holders(RenameHolderReport.__resource_files(record_path))
        except OSError:
            return ""
        directory_scoped = is_directory_scoped(record_path)
        standing_inside = directory_scoped and RenameHolderReport.__is_working_directory_inside(record_path.parent)
        return RenameHolderReport.__sentence(holders, directory_scoped, standing_inside)

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
    def __is_lock_refusal(error: BaseException) -> bool:
        """Whether ``error``, or the failure it was raised from, is Windows refusing over a handle.

        :param error: why the rename failed.
        :returns: whether someone holding a file is the likely reason.
        """
        return any(
            isinstance(candidate, OSError) and getattr(candidate, "winerror", None) in TRANSIENT_LOCK_ERRORS
            for candidate in (error, error.__cause__)
        )

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

    @staticmethod
    def __sentence(holders: tuple[FileHolder, ...], directory_scoped: bool, standing_inside: bool) -> str:
        """Say who the holders are.

        :param holders: who holds the resource's files.
        :param directory_scoped: whether the rename was of a folder.
        :param standing_inside: whether this process's working directory is in that folder.
        :returns: the sentence(s).
        """
        own = os.getpid()
        others = list(dict.fromkeys(holder.name for holder in holders if holder.pid != own))
        parts: list[str] = []
        if others:
            parts.append(HELD_BY_OTHERS.format(names=", ".join(others)))
        if any(holder.pid == own for holder in holders):
            parts.append(HELD_BY_REHUCO)
        if standing_inside:
            parts.append(HELD_BY_OWN_DIRECTORY)
        if not parts:
            parts.append(FOLDER_HELD_BY_NOBODY if directory_scoped else HELD_BY_NOBODY)
        return " ".join(parts)
