"""What the open ``.rehuco`` overlaps, as the main window's banner says it (#498).

A record must be managed by at most one root. Adding a root inside another, or containing one, is refused; but a file
can already nest when it is opened (an older or hand-edited one, neither refused nor rewritten), and nesting can
appear on disk after the check ran, so the overlap is **flagged wherever it is seen**:

- the roots as spelled, on the GUI thread, the moment a file is opened or its roots are edited;
- the roots through their links, on a daemon thread (:class:`~.root_overlap_check.RootOverlapCheck`), a moment
  later -- a junction, a ``subst`` drive, a mapped drive against its share;
- the roots a scan met inside its own and left out, and the records it found under a second name.

**It always describes the open file**: following another file starts over, so switching to a catalog whose roots
are clean takes the banner down, and a late answer about the previous file is dropped by serial. Nothing here stops
an edit: the remedy is removing one of the two roots, and the scans keep a record to one row meanwhile.
"""

from collections.abc import Collection
from typing import Final
from uuid import UUID

from PySide6.QtCore import QObject, Signal
from rehuco_core import HardlinkedRecord, RehucoFile, RootOverlap, root_path_key

from .root_overlap_check import RootOverlapCheck


class RootOverlaps(QObject):
    """The overlaps of the open ``.rehuco``'s roots, and the records a scan found under two names.

    :param parent: optional Qt parent.
    """

    changed: Signal = Signal()
    """What :attr:`messages` says may have changed."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__check: Final = RootOverlapCheck(self)
        self.__check.answered.connect(self.__on_checked)
        self.__file: RehucoFile | None = None
        self.__serial = 0
        self.__spelled: tuple[RootOverlap, ...] = ()
        self.__resolved: tuple[RootOverlap, ...] = ()
        self.__met: set[tuple[UUID, UUID]] = set()
        """``(scanned root, root met inside it)`` pairs the scans reported."""
        self.__hardlinked: list[HardlinkedRecord] = []

    @property
    def messages(self) -> list[str]:
        """One sentence per overlap and one for the records with a second name -- nothing while all is clean."""
        lines = [
            f"Roots overlap: {overlap.message}. Its records are cataloged under the inner root only."
            for overlap in self.__overlaps()
        ]
        if self.__hardlinked:
            count = len(self.__hardlinked)
            lines.append(
                f"{count} record{'s' if count != 1 else ''} reached under a second name (a hardlink) "
                f"{'are' if count != 1 else 'is'} cataloged once, under one of the names; the log names them."
            )
        return lines

    @property
    def duplicates(self) -> frozenset[UUID]:
        """The roots that duplicate an earlier one -- the later root of each overlapping pair, the one Add Root would
        refuse now -- which the Roots view draws in red."""
        if self.__file is None:
            return frozenset()
        by_key = {root_path_key(root.path): root.root_id for root in self.__file.roots}
        found = (by_key.get(root_path_key(overlap.other)) for overlap in self.__overlaps())
        return frozenset(root_id for root_id in found if root_id is not None)

    def follow(self, file: RehucoFile | None, unreachable: Collection[UUID], *, keep_scans: bool = False) -> None:
        """Describe ``file`` from now on: its roots as spelled at once, through their links a moment later.

        :param file: the open file, or ``None`` once none is.
        :param unreachable: the roots not to resolve -- those the cache holds unreachable.
        :param keep_scans: whether what the scans reported still holds -- the same catalog, its roots edited; then
            only what concerns roots still in it is kept.
        """
        self.__file = file
        self.__serial = 0
        self.__resolved = ()
        if not keep_scans or file is None:
            self.__met.clear()
            self.__hardlinked.clear()
        else:
            ids = {root.root_id for root in file.roots}
            self.__met = {pair for pair in self.__met if pair[0] in ids and pair[1] in ids}
            self.__hardlinked = [
                pair for pair in self.__hardlinked if pair.kept_root in ids and pair.dropped_root in ids
            ]
        self.__spelled = () if file is None else file.overlaps
        if file is not None and file.count > 1:
            self.__serial = self.__check.among(file.roots, unreachable)
        self.changed.emit()

    def scan_finished(
        self, root_id: UUID, met_roots: Collection[UUID], hardlinked: Collection[HardlinkedRecord]
    ) -> None:
        """Take in what a scan of the open file reported -- replacing what its last scan reported, so a nesting undone
        on disk, or a hardlink removed, takes its flag down with the next scan.

        :param root_id: the root it scanned.
        :param met_roots: the other roots it found inside and left out.
        :param hardlinked: the records it found under a second name.
        """
        met = {pair for pair in self.__met if pair[0] != root_id} | {(root_id, other) for other in met_roots}
        linked = [pair for pair in self.__hardlinked if root_id not in (pair.kept_root, pair.dropped_root)]
        linked.extend(pair for pair in hardlinked if pair not in linked)
        if met == self.__met and linked == self.__hardlinked:
            return
        self.__met = met
        self.__hardlinked = linked
        self.changed.emit()

    def stop(self) -> None:
        """Deliver no more answers from a check still running -- the window is going."""
        self.__check.stop()

    def __overlaps(self) -> list[RootOverlap]:
        """Every overlap known, spelled, through links or met by a scan, each pair once."""
        overlaps: list[RootOverlap] = []
        seen: set[tuple[UUID, str]] = set()
        for overlap in (*self.__spelled, *self.__resolved, *self.__met_overlaps()):
            key = (overlap.root.root_id, root_path_key(overlap.other))
            if key not in seen:
                seen.add(key)
                overlaps.append(overlap)
        return overlaps

    def __met_overlaps(self) -> list[RootOverlap]:
        """The scans' pairs as overlaps, the root earlier in the file first -- the way the spelled check words them."""
        if self.__file is None:
            return []
        roots = {root.root_id: (at, root) for at, root in enumerate(self.__file.roots)}
        overlaps: list[RootOverlap] = []
        for outer, inner in self.__met:
            if outer not in roots or inner not in roots:
                continue
            (outer_at, outer_root), (inner_at, inner_root) = roots[outer], roots[inner]
            if outer_at < inner_at:
                overlaps.append(RootOverlap(outer_root, inner_root.path, encloses=True))
            else:
                overlaps.append(RootOverlap(inner_root, outer_root.path, encloses=False))
        return overlaps

    def __on_checked(self, serial: int, overlaps: tuple[RootOverlap, ...]) -> None:
        """Take in the check through links, unless the file it was about is no longer the one followed."""
        if serial != self.__serial or not overlaps:
            return
        self.__resolved = overlaps
        self.changed.emit()
