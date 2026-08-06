"""Where the resources are: the recursive walk that finds `.rehu` records under a folder (#242).

The counterpart of `rehuco_core.rehu_content_files`, one level out. That module answers *what one
resource's content is*, starting from a record; this one answers *where the records are*, starting from
a folder somebody pointed at. The checksum sweep is its first caller and the catalog cache
([[data-model#scan-and-staleness]]) is the next, which is why it is named for the catalog rather than
for the sweep.

**It says what it could not see** (#245), in the shape `rehuco_core.rehu_content_files` already
established: an offline branch of a mount costs its own subtree and is *named*, rather than silently
reducing the answer -- because a catalog that lists nothing and a catalog that would not list are the
same sentence otherwise, and the second one is the lie. Whether that is fatal is the caller's to
decide, through :meth:`CatalogEnumeration.require_reachable`.

Core-side and GUI-free: no setting is read here, and a folder to start from is always a parameter.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .constants import REHU_SUFFIX
from .rehu_content_files import MAX_NAMED_UNREADABLE, ContentUnreachableError

CatalogCheckpoint = Callable[[], None]
"""What a walk calls to ask whether it should still be running.

Called once per directory, immediately before its listing, and **never caught** -- the same contract
:data:`~rehuco_core.ChecksumCheckpoint` documents, for the same reason: a cancel that a walk swallowed
is a walk that cannot be stopped. Per directory rather than per entry because a listing is this walk's
unit of work, and a per-entry call would take a lock millions of times to buy nothing."""


@dataclass(frozen=True, slots=True)
class CatalogEnumeration:
    """What one catalog walk found, and what it could not see (#242, #245).

    The shape of :class:`~rehuco_core.ContentEnumeration`, deliberately: an unreachable resource
    directory and an unreachable catalog root are the same condition seen from two distances, and a
    caller that has learned one vocabulary should not have to learn a second.

    :param root: the folder the walk started from.
    :param resources: the ``.rehu`` paths found, in a stable order.
    :param unreadable: the directories that would not list, :attr:`root` itself included when the walk
        never started at all.
    """

    root: Path
    resources: list[Path]
    unreadable: tuple[Path, ...] = ()

    @property
    def reachable(self) -> bool:
        """Whether the root itself listed -- the difference between *no resources* and *away*."""
        return self.root not in self.unreadable

    @property
    def complete(self) -> bool:
        """Whether every directory under the root listed, so :attr:`resources` is the whole catalog."""
        return not self.unreadable

    def require_reachable(self) -> None:
        """Refuse when the root itself could not be read.

        The one refusal a sweep makes: a branch it cannot list costs that branch's resources and is
        reported, while a root it cannot list means the run has nothing to say at all
        ([[mounts-and-storage#offline-mounts]]).

        :raises ContentUnreachableError: the root would not list.
        """
        if not self.reachable:
            raise ContentUnreachableError(f"The folder could not be read: {self.root}")

    def unreadable_text(self) -> str:
        """The unreadable directories, for a sentence a reader can act on.

        :returns: up to :data:`~rehuco_core.rehu_content_files.MAX_NAMED_UNREADABLE` of them, and a
            count of whatever is left.
        """
        named = ", ".join(str(directory) for directory in self.unreadable[:MAX_NAMED_UNREADABLE])
        remaining = len(self.unreadable) - MAX_NAMED_UNREADABLE
        return named if remaining <= 0 else f"{named} (and {remaining} more)"


class CatalogScanner:  # pylint: disable=too-few-public-methods
    """Finds every ``.rehu`` record under a folder ([[data-model#resource-scoping]], #242).

    **Every record counts, at any depth** -- a directory-scoped ``info.rehu``, a file-scoped
    ``foo.rehu``, several of either in one directory. A record's own directory is descended like any
    other, because a nested record is not a scan boundary ([[data-model#resource-scoping]]) and the
    sweep is asked to find it. Type-directed descent -- a tutorial terminating the walk where a
    collection does not ([[data-model#scan-and-staleness]]) -- would mean reading every record to decide
    where to stop, and belongs with the catalog cache that has somewhere to keep what it read.

    **A nested resource's content is verified twice, and that is the accepted answer.** Under #226 a
    ``sub/info.rehu``'s content is also the enclosing ``info.rehu``'s content, so a sweep that finds both
    records hashes ``sub/video.mp4`` into each of them. The alternative -- letting the inner record claim
    the bytes -- would leave the outer record's entry for them permanently unverified, which is a hole in
    a verification record rather than a saving.

    **It excludes nothing.** ``EXCLUDED_FILE_PATTERNS`` is a rule about *content* files, matched against
    junk a browser or a Mac left behind; no ``.rehu`` can match one, and letting the pattern list decide
    which resources a sweep can see would make an unrelated settings edit hide resources from
    verification. The list is handed to each resource's run instead, where it means something.

    **A symlinked directory is never descended**, matching `rehuco_core.rehu_content_files`: one
    pointing at an ancestor would loop the walk forever, and one pointing sideways would sweep the same
    resources twice under two names. A symlink *to* a ``.rehu`` file is a record like any other, because
    it is a file the caller can open.

    :param root: the folder to walk.
    :param checkpoint: called once per directory before its listing, or ``None`` for a walk nobody can
        stop.
    """

    def __init__(self, root: Path, *, checkpoint: CatalogCheckpoint | None = None) -> None:
        self.__root: Final = root
        self.__checkpoint: Final = checkpoint

    def scan(self) -> CatalogEnumeration:
        """Walk :attr:`root`, collecting the records under it and the directories that would not list.

        :returns: what the walk found; see :func:`enumerate_catalog_resources` for the full order and
            failure-handling contract.
        """
        resources: list[Path] = []
        unreadable: list[Path] = []
        pending = [self.__root]
        while pending:
            current = pending.pop()
            if self.__checkpoint is not None:
                self.__checkpoint()
            resources.extend(self.__read_directory(current, pending, unreadable))
        return CatalogEnumeration(self.__root, sorted(resources, key=str), tuple(unreadable))

    @staticmethod
    def __read_directory(directory: Path, pending: list[Path], unreadable: list[Path]) -> list[Path]:
        """Read one directory, appending its subdirectories to ``pending`` for later.

        :func:`os.scandir` rather than :meth:`~pathlib.Path.iterdir`, and for the reason
        `rehuco_core.rehu_content_files` gives at length: the listing already knows whether an entry is
        a directory, where ``iterdir`` would cost a ``stat`` per entry to learn it -- and a catalog walk
        crosses far more directories than a single resource's does.

        A directory that will not list is recorded rather than swallowed, whatever the reason: an
        unmapped drive raises :class:`FileNotFoundError` where a refused share raises
        :class:`PermissionError`, and both take their whole subtree with them (#245).

        :param directory: the directory to read.
        :param pending: the walk's stack of directories still to visit, appended to in place.
        :param unreadable: the walk's record of what would not list, appended to in place.
        :returns: the ``.rehu`` paths in that one directory, unsorted.
        """
        records: list[Path] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(directory / entry.name)
                    elif entry.is_file() and os.path.splitext(entry.name)[1].lower() == REHU_SUFFIX:
                        records.append(directory / entry.name)
        except OSError:
            unreadable.append(directory)
            return []
        return records


def enumerate_catalog_resources(root: Path, *, checkpoint: CatalogCheckpoint | None = None) -> CatalogEnumeration:
    """Find every ``.rehu`` record under ``root`` -- where the resources are, not what they hold.

    :param root: the folder to walk.
    :param checkpoint: called once per directory before its listing, so a long walk over a mount can be
        cancelled; whatever it raises is left to escape.
    :returns: the records, sorted by path so an interrupted walk resumes over the same order it left,
        **and the directories that would not list**. An unreadable branch contributes nothing rather
        than raising, but it is named, so no caller has to mistake an offline mount for an empty
        catalog (#245).
    """
    return CatalogScanner(root, checkpoint=checkpoint).scan()
