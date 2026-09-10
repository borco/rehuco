"""Rearranges one resource's screenshots on disk ([[data-model#image-meanings]], #72).

The write-side sibling of `RehuDocumentImageScanner`, resolving the same ``(directory, stem)`` from
the model and handing it to `rehuco_core.renumber_screenshots`. The concrete side of the field
toolkit's `ImageOrganizer` protocol: the curation editor depends on that interface and stays unaware
of the ``<stem>NN`` convention, exactly as it stays unaware of it when *listing*.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from rehuco_core import DEFAULT_DELETER, Deleter, convert_screenshot, delete_screenshot, renumber_screenshots

from ..settings.screenshot_deletion_settings import shared_screenshot_deletion_settings
from ..settings.screenshot_patterns_settings import shared_screenshot_patterns_settings
from .recycle_bin_deleter import RecycleBinDeleter

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

    def convert(self, path: Path) -> dict[str, str]:
        """Rename ``path`` into this resource's numbered set, free slot or appended (#265, #270).

        The patterns are read live from the shared settings, for the same reason
        :attr:`deletes_to_trash` is: a page Saved after this organizer was built is still the user's
        current answer about which names are screenshots at all.

        :param path: the un-converted screenshot to number.
        :returns: ``{old filename: new filename}`` -- one entry, so the curated-out list follows the
            rename the same way it follows a reorder's.
        :raises OSError: the rename failed, or was refused -- including the refusal :meth:`__location`
            raises for a path-less document or a legacy ``.tc``, which reaches this one first and says
            the same thing `~rehuco_core.convert_screenshot` would.
        :raises LookupError: ``path`` matches no configured pattern; see the protocol.
        :raises ValueError: the numbered set is full.
        """
        _, stem = self.__location()
        converted = convert_screenshot(path, stem, shared_screenshot_patterns_settings().screenshot_name_patterns)
        return {path.name: converted.name}

    @property
    def deletes_to_trash(self) -> bool:
        """Whether the next :meth:`remove` called with no explicit ``deleter`` will try to send the
        file to the Recycle Bin / Trash, per the **Move deleted images to the Recycle Bin** setting --
        read live rather than cached, so a page Saved after this organizer was built is still honoured.
        Purely informational: the confirm dialog is the only reader (#291).
        """
        return shared_screenshot_deletion_settings().use_recycle_bin

    def remove(self, path: Path, remaining: Sequence[Path], deleter: Deleter | None = None) -> dict[str, str]:
        """Delete ``path`` and renumber ``remaining`` onto the slot it vacated.

        The delete comes first and the renumbering second, so a delete that fails leaves the set
        untouched rather than closing a gap around a file that is still there.

        :param path: the screenshot to delete.
        :param remaining: every other screenshot, in the order wanted.
        :param deleter: how ``path`` is actually removed; ``None`` (the default) resolves the
            **Move deleted images to the Recycle Bin** setting into a `RecycleBinDeleter` or a plain
            unlink -- an explicit deleter is how a caller overrides that, e.g. the dock's permanent-
            delete fallback after a `~rehuco_core.NoTrashBinError` (#291).
        :returns: ``{old filename: new filename}`` for each survivor actually renamed.
        :raises OSError: if the delete or the renumbering that follows it failed -- or the
            rearrangement was refused outright (:meth:`__location`), before anything is deleted.
        """
        directory, stem = self.__location()
        delete_screenshot(path, deleter if deleter is not None else self.__default_deleter())
        return renumber_screenshots(directory, stem, remaining)

    def __default_deleter(self) -> Deleter:
        """The deleter :meth:`remove` uses absent an explicit one, per the current setting.

        :returns: a `RecycleBinDeleter` when **Move deleted images to the Recycle Bin** is on,
            otherwise `~rehuco_core.DEFAULT_DELETER`.
        """
        return RecycleBinDeleter() if self.deletes_to_trash else DEFAULT_DELETER

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
