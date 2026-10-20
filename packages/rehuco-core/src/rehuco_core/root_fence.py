"""The other roots a scan must not enter -- the guarantee that a record has one row (#498).

Refusing a nested root when it is added (:class:`~rehuco_core.RootOverlap`) is only the early message: nesting can
appear after the check ran -- a root folder moved into another outside the app, a share mounted inside a root, a
drive letter re-pointed, a hand-edited ``.rehuco``. So the scan itself never descends into another root of the same
catalog, and the inner root keeps its records however the nesting arose.

**A directory is matched by identity, not spelling**: its ``(st_dev, st_ino)`` against each other root's, so case,
a mapped drive against its share's path, a ``subst`` drive or a link spelling the root all match. A root whose
identity is unusable -- it would not stat, or reports a zero inode as some SMB servers do -- falls back to its
spelled path, normalized and never resolved (#511), and says so in the log; covering that fully is #453's
fingerprint. The identities are read once, when the scan starts, on its worker.

**Only a directory whose name could be a root's is stat'ed.** An extra ``stat`` per directory cost a third more walk
time on the NAS (1871 directories, 4.9 ms against 6.5 ms each, warm). A directory that is another root carries that
root's last component as its name -- as spelled, or as its link resolves -- so only those names are checked by
identity, unless some other root has no name at all (a drive's or a share's top), when every directory is. A root
mounted inside another under a different name -- a Linux bind mount, which ``realpath`` does not see through -- slips
past that filter; the owner's machines are Windows and a NAS, where a mounted folder carries its own name.
"""

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from os import path as os_path
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import UUID

from .root_overlap import root_path_key

if TYPE_CHECKING:
    from .rehudb import CatalogRoot

LOG: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RootFence:
    """The other roots of a catalog, as a scan of one root compares its directories against them.

    :param identities: each other root's ``(st_dev, st_ino)``, for those whose identity is usable.
    :param spellings: each other root's spelled key (:func:`~rehuco_core.root_path_key`), for all of them.
    :param names: the case-folded last components a directory must carry to be stat'ed.
    :param every_directory: whether every directory is stat'ed regardless of its name -- some root has none.
    """

    identities: dict[tuple[int, int], UUID]
    spellings: dict[str, UUID]
    names: frozenset[str]
    every_directory: bool

    @staticmethod
    def read(others: Sequence[CatalogRoot]) -> RootFence:
        """Read the other roots' identities -- **touches the disk**, so on the scan's worker, once.

        A root the cache holds unreachable is not read: it takes part spelled only, rather than having the scan
        wait out a switched-off share's timeout before it starts.

        :param others: the catalog's roots other than the one scanned.
        :returns: the fence.
        """
        identities: dict[tuple[int, int], UUID] = {}
        spellings: dict[str, UUID] = {}
        names: set[str] = set()
        every_directory = False
        for root in others:
            spellings[root_path_key(root.path)] = root.root_id
            spelled_name = RootFence.__name(str(root.path))
            if spelled_name is None:
                every_directory = True
            else:
                names.add(spelled_name)
            if root.reachable is False:
                continue
            try:
                status = os.stat(root.path)
                resolved = os_path.realpath(root.path)
            except (OSError, ValueError) as error:
                LOG.info("The root %s could not be read (%s); a scan matches it by spelling only.", root.path, error)
                continue
            if status.st_ino == 0:
                LOG.info("The root %s reports no file identity; a scan matches it by its spelling only.", root.path)
                continue
            identities[(status.st_dev, status.st_ino)] = root.root_id
            resolved_name = RootFence.__name(resolved)
            if resolved_name is None:
                every_directory = True
            else:
                names.add(resolved_name)
        return RootFence(identities, spellings, frozenset(names), every_directory)

    def match(self, directory: Path, *, by_name: bool = True) -> UUID | None:
        """Which other root a directory is, if any -- a ``stat`` only when its name could be one's.

        :param directory: a directory the walk is about to queue.
        :param by_name: whether to ``stat`` only a directory whose name could be a root's; ``False`` always does, for
            the one directory a scan starts from, which may be another root under a second spelling.
        :returns: the root's id, or ``None`` for a directory the walk may enter.
        """
        spelled = self.spellings.get(root_path_key(directory))
        if spelled is not None:
            return spelled
        if not self.identities or (by_name and not (self.every_directory or directory.name.casefold() in self.names)):
            return None
        try:
            # a queued directory is never a link (the walk skips those); the root a scan starts from may be spelled
            # through one, and is what it points at
            status = os.stat(directory, follow_symlinks=not by_name)
        except OSError:
            return None  # the walk's own listing of it says what is wrong
        return self.identities.get((status.st_dev, status.st_ino))

    @staticmethod
    def __name(path: str) -> str | None:
        """A root's last component, case-folded, or ``None`` for a root with none (``D:\\``, ``\\\\host\\share``)."""
        _, rest = os_path.splitdrive(os_path.normpath(path))
        name = os_path.basename(rest.rstrip("/\\"))
        return name.casefold() if name else None
