"""Reordering a ``.rehu`` resource's screenshots on disk ([[data-model#image-meanings]], #72).

The writer counterpart of `rehuco_core.rehu_screenshots`: where that *lists* the ``<stem>NN`` siblings
a resource already has, this renames them so their order on disk matches an order a caller asked for.
That is the whole mechanism behind moving a screenshot and behind deleting one -- a resource's
screenshot order **is** its numbering, so a move is a rename and a delete is an unlink followed by
closing the gap it left.

Core-side and GUI-free, like the scanner beside it: the caller resolves ``directory`` and ``stem``
however it needs to and hands over the order it wants.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Protocol

TEMP_SUFFIX: Final = ".rehuco-reorder"
"""Appended to a screenshot's filename while it is parked mid-renumbering (:class:`ScreenshotRenumberer`).

Chosen so a parked file is invisible to every scanner that walks the directory: it is the *whole*
extension of the parked name, so `rehuco_core.scan_rehu_screenshot_files` -- which requires one of
`IMAGE_EXTENSIONS` -- cannot match it, and neither can the legacy scanner. A file left parked by a
crash mid-renumbering is therefore not mistaken for a screenshot; it shows up in the content walk
instead, which is the honest place for a file nothing else claims.
"""


def plan_screenshot_renumbering(stem: str, ordered: Sequence[Path]) -> dict[str, str]:
    """Work out which screenshots have to be renamed for ``ordered`` to be the order on disk.

    Slot ``i`` is ``<stem>NN`` with ``NN`` the zero-padded position in ``ordered``, **counting from
    00**: a resource's canonical set runs ``00, 01, 02, ...``, so a set that starts at ``01``, or one
    with a hole in the middle, is renumbered rather than left with the gap. Each file keeps its own
    extension, since a slot names a position and not a format -- moving a ``.png`` above a ``.jpg``
    swaps their numbers and leaves both files decodable.

    Pure: reads nothing and writes nothing. :func:`renumber_screenshots` is what carries it out.

    :param stem: the filename base every screenshot shares (e.g. ``"info"``).
    :param ordered: the screenshots in the order wanted, as paths; only their names are read.
    :returns: ``{current filename: wanted filename}`` for every file that has to move, and nothing for
        the ones already in the right slot.
    """
    renames = {}
    for index, path in enumerate(ordered):
        wanted = f"{stem}{index:02d}{path.suffix}"
        if wanted != path.name:
            renames[path.name] = wanted
    return renames


def renumber_screenshots(directory: Path, stem: str, ordered: Sequence[Path]) -> dict[str, str]:
    """Rename ``directory``'s screenshots so their numbering matches ``ordered``.

    :param directory: the resource's directory, which every name is resolved against.
    :param stem: the filename base every screenshot shares.
    :param ordered: the screenshots in the order wanted; a file left out of it is simply not renamed,
        so a caller closing a gap passes the survivors and unlinks the dropped one itself.
    :returns: ``{old filename: new filename}`` for every file actually renamed, so a caller holding
        names rather than paths (e.g. a document's hidden-screenshot list) can follow them.
    :raises OSError: if a rename fails, after the rollback has been attempted.
    """
    renames = plan_screenshot_renumbering(stem, ordered)
    if renames:
        ScreenshotRenumberer(directory).apply(renames)
    return renames


class Deleter(Protocol):  # pylint: disable=too-few-public-methods
    """How one screenshot's file is actually made to disappear ([[plugins#tutorial-plugin]], #291).

    A plain protocol so the destination -- straight gone, or by way of the Recycle Bin -- is the
    caller's choice: core only ever asks for one file to be deleted, never how (#265).
    """

    def delete(self, path: Path) -> None:
        """Remove ``path``.

        :raises NoTrashBinError: a Recycle-Bin-capable implementation's own way of refusing when no
            bin is reachable for ``path`` -- never a silent fall-through to a permanent delete.
        """


class NoTrashBinError(OSError):
    """Raised by a :class:`Deleter` that could not reach a Recycle Bin / Trash for a path (#291).

    Core defines it, though only agent-side deleters (``send2trash``, kept out of this dependency-free
    package) ever raise it: a shared vocabulary is what lets a caller catch this one case -- a Windows
    SMB share, the mounted NAS ([[mounts-and-storage#offline-mounts]]) -- and offer a permanent delete
    for just that one action, without either side depending on the other's deleter implementations.
    """


class UnlinkDeleter:  # pylint: disable=too-few-public-methods
    """The default :class:`Deleter`: a plain, permanent `Path.unlink`."""

    def delete(self, path: Path) -> None:
        """Unlink ``path``."""
        path.unlink()


DEFAULT_DELETER: Final = UnlinkDeleter()
"""What :func:`delete_screenshot` and its callers fall back to absent a Recycle-Bin-capable one -- #291
is what gives the agent that one to inject instead."""


def delete_screenshot(path: Path, deleter: Deleter = DEFAULT_DELETER) -> None:
    """Delete one screenshot through ``deleter``.

    :param path: the screenshot to delete.
    :param deleter: how the file is actually removed; the Recycle Bin choice is the caller's (#291).
    """
    deleter.delete(path)


# a class for one public method, because the rollback it needs cannot be a module-level helper:
# a leading underscore outside a class is not privacy, so the convention here is a real class with
# `__`-mangled methods ([[appendices.code-conventions]]) -- the same shape as TcScreenshotScanner
class ScreenshotRenumberer:  # pylint: disable=too-few-public-methods
    """Carries out a screenshot rename plan inside one directory, parking each file on the way.

    Every rename goes through a parked name (:data:`TEMP_SUFFIX`) before going on to its slot. Two
    passes rather than one is what makes *any* rearrangement work without this class, or its caller,
    reasoning about cycles: a plain swap has each file's target occupied by the other, and a rotation
    has every target occupied, so a single pass would need an ordering that does not exist. With every
    mover parked first, no target is occupied when it is claimed.

    A failure in either pass **rolls back** what it had already done, so a resource is never left half
    renumbered -- one screenshot sitting in another's slot is worse than the move not happening, since
    the numbering *is* the order and nothing else records what it was.

    :param directory: the directory every name in a plan is resolved against.
    """

    def __init__(self, directory: Path) -> None:
        self.__directory: Final = directory

    def apply(self, renames: Mapping[str, str]) -> None:
        """Carry out ``renames``, parking every file before any of them claims a slot.

        :param renames: ``{old filename: new filename}``, as :func:`plan_screenshot_renumbering`
            returns.
        :raises OSError: if a rename fails, after the rollback has been attempted.
        """
        parked: list[tuple[Path, Path]] = []
        try:
            for old_name in renames:
                source = self.__directory / old_name
                temporary = self.__directory / (old_name + TEMP_SUFFIX)
                source.replace(temporary)
                parked.append((source, temporary))
            while parked:
                # read, move, *then* drop: dropping first would take the file that is mid-rename off
                # the rollback list, leaving exactly the one that failed parked under a name no
                # scanner recognizes
                source, temporary = parked[-1]
                temporary.replace(self.__directory / renames[source.name])
                parked.pop()
        except OSError:
            self.__rollback(parked)
            raise

    @staticmethod
    def __rollback(parked: list[tuple[Path, Path]]) -> None:
        """Return every still-parked file to the name it came from, best effort.

        Best effort by necessity: this runs because a rename has already failed, so the disk is in
        whatever state caused that -- an offline mount ([[mounts-and-storage#offline-mounts]]), a full
        volume, a file another process holds open. Restoring what can be restored beats abandoning
        every parked file under a name no scanner recognizes; a second failure here leaves that one
        file parked and lets the original error be the one the caller sees, since that is the one
        explaining what happened.

        :param parked: the ``(original, parked)`` pairs still awaiting their slot.
        """
        for source, temporary in reversed(parked):
            try:
                temporary.replace(source)
            except OSError:
                continue
