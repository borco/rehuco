"""Rearranges one resource's screenshots on disk ([[data-model#image-meanings]], #72).

The write-side sibling of `RehuDocumentImageScanner`, resolving the same ``(directory, stem)`` from
the model and handing it to `rehuco_core.renumber_screenshots`. The concrete side of the field
toolkit's `ImageOrganizer` protocol: the curation editor depends on that interface and stays unaware
of the ``<stem>NN`` convention, exactly as it stays unaware of it when *listing*.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from rehuco_core import renumber_screenshots

if TYPE_CHECKING:
    from .rehu_document_model import RehuDocumentModel


class RehuDocumentImageOrganizer:
    """Renames one resource's screenshots to match an order asked for ([[data-model#image-meanings]]).

    Refuses outright while the document is a legacy ``.tc`` ([[acquisition-tooling#tc-to-rehu]]): the
    files it shows are the *pre-conversion* originals under tc4's own naming schemes, which conversion
    still has to read and back up, so renumbering them into ``<stem>NN`` slots early would be a
    conversion nobody asked for -- performed without the backups the real one takes. A ``.tc``
    document is locked and its editor disabled, so this is the second lock rather than the first.

    :param model: the document whose screenshots this organizer rearranges.
    """

    def __init__(self, model: RehuDocumentModel) -> None:
        self.__model: Final = model

    def reorder(self, ordered: Sequence[Path]) -> dict[str, str]:
        """Renumber this resource's screenshots so ``ordered`` is the order on disk.

        :param ordered: every screenshot, in the order wanted.
        :returns: ``{old filename: new filename}`` for each one actually renamed.
        :raises OSError: if the rearrangement failed -- or was refused outright
            (:meth:`__location`), since a refusal that answered like a no-op would let the caller's
            rows and the directory drift apart. The resource is left as it was either way.
        """
        directory, stem = self.__location()
        return renumber_screenshots(directory, stem, ordered)

    def remove(self, path: Path, remaining: Sequence[Path]) -> dict[str, str]:
        """Delete ``path`` and renumber ``remaining`` onto the slot it vacated.

        The unlink comes first and the renumbering second, so a delete that fails leaves the set
        untouched rather than closing a gap around a file that is still there.

        :param path: the screenshot to delete.
        :param remaining: every other screenshot, in the order wanted.
        :returns: ``{old filename: new filename}`` for each survivor actually renamed.
        :raises OSError: if the delete or the renumbering that follows it failed -- or the
            rearrangement was refused outright (:meth:`__location`), before anything is unlinked.
        """
        directory, stem = self.__location()
        path.unlink()
        return renumber_screenshots(directory, stem, remaining)

    def __location(self) -> tuple[Path, str]:
        """Where this resource's screenshots live and what they are named after.

        The same ``(path.parent, path.stem)`` `RehuDocumentImageScanner` lists from, so the names this
        writes are the names that scan reports back.

        Refusal is an exception rather than a sentinel: an empty rename map already means "nothing
        needed renaming", so answering a refusal the same way would read as success -- the model would
        move its rows while the directory stayed put. Both refusals sit behind a first lock (a
        ``.tc``'s editor is disabled, a path-less document lists no screenshots), so raising here is
        the second lock actually locking.

        :returns: the directory and filename stem.
        :raises PermissionError: a document with no path yet, or a legacy ``.tc`` (see the class
            docstring) -- an :class:`OSError`, so the editor's ordinary failure handling
            (log, reseed from disk) covers it.
        """
        path = self.__model.path
        if path is None or self.__model.document.legacy_tc:
            raise PermissionError("this resource's screenshots cannot be rearranged")
        return path.parent, path.stem
