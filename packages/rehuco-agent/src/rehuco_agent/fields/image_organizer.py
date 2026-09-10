"""The screenshot-rearranging contract the curation editor depends on ([[data-model#image-meanings]], #72).

The write-side companion of `ImageScanner`, and inverted the same way: the toolkit's editor depends on
this `Protocol`, and the concrete, model-backed ``RehuDocumentImageOrganizer`` in the ``documents``
layer implements it. That is what keeps the editor unaware of the ``<stem>NN`` naming convention it is
rearranging -- it says *which order it wants*, and something that knows where the resource lives turns
that into renames.

Both calls hand back the old-name-to-new-name mapping they carried out, because a resource's other
screenshot state is filenames rather than paths (the curated-out set,
[[data-model#image-meanings]]) and would otherwise be left pointing at names that no longer exist.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from rehuco_core import Deleter


class ImageOrganizer(Protocol):
    """What the curation editor needs to rearrange a resource's screenshots on disk (#72).

    A resource's screenshot order **is** its numbering, so there is nothing to record separately:
    both calls rename files, and the order they leave behind is the order the next scan reports.
    """

    def reorder(self, ordered: Sequence[Path]) -> dict[str, str]:  # pyright: ignore[reportReturnType]
        """Renumber this resource's screenshots so ``ordered`` is the order on disk.

        :param ordered: every screenshot, in the order wanted.
        :returns: ``{old filename: new filename}`` for each one actually renamed.
        :raises OSError: if the rearrangement failed or was refused; the resource is left as it
            was. A refusal raises rather than answering with an empty map, because an empty map
            already means "nothing needed renaming" -- a legitimate success.
        """

    def convert(self, path: Path) -> dict[str, str]:  # pyright: ignore[reportReturnType]
        """Take one pattern-matched image into the numbered set (#270).

        The third way this resource's screenshots are renamed, and the only one that changes how many
        of them hold a slot: the file keeps its bytes and its extension and gains a ``<stem>NN`` name.

        :param path: the un-converted screenshot to number.
        :returns: ``{old filename: new filename}`` -- one entry, so the curated-out set follows the
            rename exactly as it follows a reorder's.
        :raises OSError: if the rename failed, or was refused -- the resource is left as it was. The
            refusals are the ones :func:`~rehuco_core.convert_screenshot` names: a resource still a
            ``.tc``, or a chosen name already on disk.
        :raises LookupError: ``path``'s name matches no configured pattern -- it was never an
            un-converted screenshot, so this is a caller error rather than a state to report.
        :raises ValueError: the numbered set is full.
        """

    @property
    def deletes_to_trash(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether the next :meth:`remove` called with no explicit ``deleter`` will try to send the
        file to a Recycle Bin / Trash, rather than unlinking it outright -- what the confirm dialog
        reads to say which of the two is about to happen (#291)."""

    def remove(self, path: Path, remaining: Sequence[Path], deleter: Deleter | None = None) -> dict[str, str]:
        """Delete one screenshot and close the gap it leaves.

        :param path: the screenshot to delete, of either kind.
        :param remaining: every other **numbered** screenshot, in the order wanted -- an un-converted
            one holds no slot, so passing it would be asking for it to be given one (#270).
        :param deleter: how ``path`` is actually removed; ``None`` leaves the choice to the
            organizer's own configured default (:attr:`deletes_to_trash`) -- a caller passes one
            explicitly only to override it, e.g. a permanent-delete retry after a
            `~rehuco_core.NoTrashBinError` (#291).
        :returns: ``{old filename: new filename}`` for each survivor actually renamed.
        :raises OSError: if the delete or the renumbering that follows it failed, or the
            rearrangement was refused -- the same rule, and for the same reason, as :meth:`reorder`.
        """
        ...  # pylint: disable=unnecessary-ellipsis  # a long signature is what makes an inline pyright-ignore too long
