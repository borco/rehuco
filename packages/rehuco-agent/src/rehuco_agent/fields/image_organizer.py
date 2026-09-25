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

    def acquire(self, data: bytes, extension: str, slot: int | None = None) -> Path:
        """Write newly-acquired image bytes into a ``<stem>NN`` slot (#73).

        The fourth way this resource's screenshots come to exist, and the only one whose bytes come
        from outside the resource entirely -- a local file dropped on the images sub-dock, a drop's own
        image data, or a scraper's downloaded URL. ``data`` is written exactly as given: nothing here
        decodes, rescales or re-encodes it.

        :param data: the image's raw bytes.
        :param extension: the file's extension, leading dot included (e.g. ``".jpg"``).
        :param slot: the ``<stem>NN`` slot to write into; ``None`` (a plain drop) takes the next free
            one. An explicit slot (a scrape result's own numbering) may already be occupied, in which
            case the file already there is backed up first, never overwritten.
        :returns: the new file's path.
        :raises OSError: the write failed, or was refused -- including the refusal a path-less
            document or a legacy ``.tc`` raises, the same one :meth:`reorder` and :meth:`convert` do.
        :raises ValueError: ``slot`` is ``None`` and the numbered set is already full.
        """
        ...  # pylint: disable=unnecessary-ellipsis  # a long signature is what makes an inline pyright-ignore too long

    def remove(self, path: Path, remaining: Sequence[Path], deleter: Deleter | None = None) -> dict[str, str]:
        """Delete one screenshot and close the gap it leaves.

        Whether that delete is permanent, and whether it is confirmed, is not this contract's to say:
        the editor's `~rehuco_agent.delete_confirmation.confirm_delete` reads the one deletion policy
        itself (#313), so the organizer only ever carries out a delete already decided on.

        :param path: the screenshot to delete, of either kind.
        :param remaining: every other **numbered** screenshot, in the order wanted -- an un-converted
            one holds no slot, so passing it would be asking for it to be given one (#270).
        :param deleter: how ``path`` is actually removed; ``None`` leaves the choice to the
            organizer's own configured default -- a caller passes one explicitly only to wrap or
            override it, e.g. the editor's `~rehuco_agent.asking_deleter.AskingDeleter` around it
            (#301).
        :returns: ``{old filename: new filename}`` for each survivor actually renamed.
        :raises OSError: if the delete or the renumbering that follows it failed, or the
            rearrangement was refused -- the same rule, and for the same reason, as :meth:`reorder`.
        """
        ...  # pylint: disable=unnecessary-ellipsis  # a long signature is what makes an inline pyright-ignore too long
