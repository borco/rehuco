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

    def remove(self, path: Path, remaining: Sequence[Path]) -> dict[str, str]:  # pyright: ignore[reportReturnType]
        """Delete one screenshot and close the gap it leaves.

        :param path: the screenshot to delete.
        :param remaining: every other screenshot, in the order wanted.
        :returns: ``{old filename: new filename}`` for each survivor actually renamed.
        :raises OSError: if the delete or the renumbering that follows it failed, or the
            rearrangement was refused -- the same rule, and for the same reason, as :meth:`reorder`.
        """
