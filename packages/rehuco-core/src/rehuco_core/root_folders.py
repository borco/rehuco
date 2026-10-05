"""Listing one folder under a ``.rehuco``'s root, by ``(root id, relative path)`` (#378).

The Roots view reads every folder through :meth:`RootFolderLister.list`, and nothing else in it touches the
disk. That one function is the seam Release 0.4.0 swaps for the access seam's file listing
([[nodes#access-seam]]), so a root another node serves browses the same way: the question is asked by root id
and relative path, never by an absolute path the caller built.

Core-side and GUI-free: the roots, the rename coordinator and the junk globs are all parameters.
"""

from collections.abc import Iterable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Final
from uuid import UUID

from .constants import EXCLUDED_FILE_PATTERNS
from .rehu_file_kinds import DirectoryClassifier, DirectoryListing
from .rehuco_file import RehucoRoot
from .rename_coordination import RenameCoordinator

BROWSING_RECORD: Final = Path("browsing.rehu")
"""The record path a listing is classified from. It names no resource: its parent is ``.``, which no directory a
root lists ever equals, so no folder is ever "a resource's own directory" -- the classifier answers for entries
as they would be to a stranger, which is all the Roots view reads (whether an entry is a folder, and its
:class:`~rehuco_core.rehu_file_kinds.FileType`)."""


# one method is the whole of it -- list a folder -- and it is the seam the access seam replaces
# pylint: disable-next=too-few-public-methods
class RootFolderLister:
    """Lists one folder of one root, under the rename coordinator's hold.

    **Never blocks a rename** ([[mounts-and-storage#out-of-band]]): each call is one ``scandir`` inside
    :meth:`~rehuco_core.RenameCoordinator.holding`, closed before it returns, so no handle is held between two
    calls and a rename waits for at most one directory read.

    Built over a snapshot of the roots, which is immutable, so one instance may be called from any thread.

    :param roots: the ``.rehuco``'s roots.
    :param coordinator: what each read is held under; ``None`` holds nothing, for a caller with no renames to yield
        to.
    :param excluded_patterns: filename globs that take a file out of content.
    """

    def __init__(
        self,
        roots: Iterable[RehucoRoot],
        *,
        coordinator: RenameCoordinator | None = None,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    ) -> None:
        self.__paths: Final = {root.root_id: root.path for root in roots}
        self.__coordinator: Final = coordinator
        self.__classifier: Final = DirectoryClassifier(BROWSING_RECORD, excluded_patterns)

    def list(self, root_id: UUID, relative: tuple[str, ...] = ()) -> DirectoryListing:
        """Read one folder.

        :param root_id: the root.
        :param relative: the folder's path under the root, one name per step; empty for the root's own folder.
        :returns: the classified listing, unsorted. An unknown root, or a folder that cannot be read, comes back
            empty and **not reachable**, never raising (#245): "the folder is gone" and "the folder is empty" are
            different answers.
        """
        root = self.__paths.get(root_id)
        if root is None:
            return DirectoryListing(Path(), reachable=False)
        holding: AbstractContextManager[None] = (
            nullcontext() if self.__coordinator is None else self.__coordinator.holding()
        )
        with holding:
            return self.__classifier.classify(root.joinpath(*relative))
