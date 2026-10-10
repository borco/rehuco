"""The Roots view's model: a ``.rehuco``'s roots, and the folders and files under them, listed on demand
(#378, [[plugins#rehuco-dock]], [[plugins#files-subdock]]).

**Lazy and off the GUI thread.** A folder is listed when a view first asks for its children
(``canFetchMore``/``fetchMore``), by :class:`~rehuco_core.RootFolderLister` on the global thread pool, and the answer
comes back through a queued signal. Until it does, the folder's column shows one *Loading* row. Never
``QFileSystemModel``, for the files sub-dock's reasons: its watcher holds handles open on Windows, and browsing must
never block a rename ([[mounts-and-storage#out-of-band]]).

**In place, never a reset.** A listing is diffed against what the node already shows, so a selection, a scroll
position and an open column's subtree survive it; a relocation renames the node it moved
(:meth:`RootsFolderModel.relocate`); a changed ``.rehuco`` inserts, removes, moves and updates root rows
(:meth:`RootsFolderModel.set_roots`).

**A node stores a name.** Its path, and the ``(root id, relative path)`` key the one listing function is asked by,
derive from its ancestors, so renaming a folder renames a whole loaded subtree by changing one node.

**An unreachable folder says so** (#245): its column holds one row naming what is wrong, never an empty list.
"""

import itertools
import time
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from os import path as os_path
from pathlib import Path
from typing import Any, Final, cast, override
from uuid import UUID

from PySide6.QtCore import (
    QAbstractItemModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QFont
from rehuco_core import (
    DIRECTORY_SCOPED_FILENAMES,
    DirectoryEntry,
    DirectoryListing,
    FileType,
    RehucoRoot,
    Relocation,
    RootFolderLister,
    RootStorage,
    is_record_name,
    natural_sort_key,
)

from ..documents.files_rows import FILE_TYPE_ICONS, checksum_tooltip_for
from ..settings.checksum_settings import shared_checksum_settings
from .root_folder_loader import RootFolderLoader
from .root_storage import (
    FOLDER_NOT_FOUND_ROW,
    ROOT_STORAGE_ICONS,
    ROOT_STORAGE_OFFLINE_ROWS,
    ROOT_STORAGE_OFFLINE_TOOLTIPS,
)
from .roots_checksum import BOOKKEEPING_KINDS, RowChecksum, row_checksum

ROOT_MIME_TYPE: Final = "application/x-rehuco-root"
"""What a dragged root is carried as: its id. Nothing else is draggable, and nothing from outside is dropped."""

LOADING_ROW: Final = "Loading..."
"""The one row a folder's column shows while its first listing is out."""

type ModelIndex = QModelIndex | QPersistentModelIndex


class RootsNodeKind(StrEnum):
    """What a node is. The last two are placeholder rows: a column shows one while it loads, or when it could not
    be listed, and neither can be selected."""

    ROOT = "root"
    FOLDER = "folder"
    FILE = "file"
    LOADING = "loading"
    UNREACHABLE = "unreachable"


class NodeListing(StrEnum):
    """Where a root's or folder's listing stands."""

    UNLISTED = "unlisted"
    """Never asked for."""

    PENDING = "pending"
    """A listing is out. Rows already shown stay until it lands."""

    LISTED = "listed"
    """Listed, and it was reachable."""

    UNREACHABLE = "unreachable"
    """Listed, and the folder could not be read."""


PLACEHOLDER_KINDS: Final = (RootsNodeKind.LOADING, RootsNodeKind.UNREACHABLE)

LISTABLE_KINDS: Final = (RootsNodeKind.ROOT, RootsNodeKind.FOLDER)


# a model is one cohesive surface: the tree, its lazy fetch, its in-place edits and the follow of a rename all turn
# on the same nodes, and splitting them would only pass those nodes around
# pylint: disable-next=too-many-public-methods
class RootsFolderModel(QAbstractItemModel):
    """The roots of a ``.rehuco`` and everything under them, as a single-column tree for a ``QColumnView``.

    Root rows are in the file's order, and under a root or a folder come its subfolders then its files, each in
    natural order, with no ``..`` row. Roles beyond display:

    * :attr:`ICON_PATH_ROLE`: the resource path of the row's glyph -- the storage's for a root, the file type's for
      a folder or file; nothing for a placeholder.
    * :attr:`PATH_ROLE`: a root's folder, which its row shows under its name.
    * :attr:`SIZE_ROLE` and :attr:`MODIFIED_ROLE`: a file's size in bytes and a row's modification time, as the listing
      gave them, for the preview to show without touching the disk again.
    * :attr:`CHECKSUM_ROLE`: a covered file's :class:`~rehuco_agent.rehuco.roots_checksum.RowChecksum`, as the
      record that covers it last found it (#457); ``None`` when no record covers the file.
      :attr:`BOOKKEEPING_ROLE`: whether the file is a record, a checksum file or a screenshot, which no record
      checksums.
    * :attr:`GREYED_ROLE`: whether the row is drawn greyed out -- a placeholder, or an unreachable root whose
      storage is not local. An unreachable **local** root is struck through instead (``FontRole``): a local folder
      that will not list has been deleted, where a share or a drive is merely away.

    Everything is read through the one :class:`~rehuco_core.RootFolderLister` the model was last handed, which is the
    seam Release 0.4.0 swaps for the access seam's listing.

    :param parent: optional Qt parent.
    """

    root_move_requested = Signal(object, int)
    """``(root id, row)``: a root was dropped, and should end up at ``row`` in the list as it will be. The model changes
    nothing itself -- the file owns the order -- so whoever hears this edits the file and shows the result."""

    records_listed = Signal(object, object)
    """``(folder, records)``: a folder just listed, and the absolute paths of the records that bear on it -- those it
    holds and the directory-scoped one above that manages it -- for their rows to be verified (#487). Emitted for every
    listing that could read the folder, a relist included."""

    ICON_PATH_ROLE: Final = int(Qt.ItemDataRole.UserRole)
    GREYED_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 1
    SIZE_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 2
    MODIFIED_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 3
    PATH_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 4
    CHECKSUM_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 5
    BOOKKEEPING_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 6

    @dataclass(eq=False)
    class Node:  # pylint: disable=too-many-instance-attributes
        """One row. It stores its name only; where it is derives from its ancestors.

        :param name: the row's name -- a root's label, a folder's or file's name, or a placeholder's text.
        :param kind: what the row is.
        :param parent: the row above, or ``None`` for the invisible top.
        :param file_type: what a folder or file is by shape.
        :param root: the root, for a root row.
        :param size: a file's size in bytes, when the listing had it.
        :param modified: a modification time as a POSIX timestamp, when the listing had it.
        :param checksum: what the record that covers a file says about it, when one does (#457).
        :param bookkeeping: whether a file is a record, a checksum file or a screenshot.
        :param listed_at: :func:`time.monotonic` when its listing last landed, reachable or not; ``None`` until one
            has.
        """

        name: str
        kind: RootsNodeKind
        parent: RootsFolderModel.Node | None
        file_type: FileType = FileType.GENERIC
        root: RehucoRoot | None = None
        size: int | None = None
        modified: float | None = None
        checksum: RowChecksum | None = None
        bookkeeping: bool = False
        children: list[RootsFolderModel.Node] = field(default_factory=list)
        row: int = 0
        listing: NodeListing = NodeListing.UNLISTED
        request: int = 0
        listed_at: float | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__top: Final = RootsFolderModel.Node("", RootsNodeKind.ROOT, None)
        self.__lister: RootFolderLister | None = None
        self.__loader: Final = RootFolderLoader(self)
        self.__loader.listed.connect(self.__on_listed)
        self.__serials: Final = itertools.count(1)
        self.__pending: Final[dict[int, RootsFolderModel.Node]] = {}
        self.__reorderable = False
        self.__retired: list[RootsFolderModel.Node] = []
        """Rows taken out of the tree. Qt may still hold an index to one for a moment, and ``internalPointer`` does
        not keep its object alive, so they are held until the event loop has turned."""

    # region the roots

    def set_roots(self, roots: Sequence[RehucoRoot], lister: RootFolderLister | None) -> None:
        """Show ``roots``, in this order, changing only what differs from what is shown.

        A removed root's rows are removed, a new root is inserted and listed at once -- so an away root reads as
        away without being clicked -- and a root that moved is moved. A root whose label or storage changed is
        updated in place; one whose folder changed drops what it had listed and lists again. The model is never reset.

        :param roots: the ``.rehuco``'s roots, in its order; empty when no catalog is open.
        :param lister: what lists a folder, over these roots.
        """
        self.__lister = lister
        top = self.__top
        wanted = {root.root_id for root in roots}
        for row in reversed(range(len(top.children))):
            if self.__own_root(top.children[row]).root_id not in wanted:
                self.__remove(top, row)
        for position, root in enumerate(roots):
            node = top.children[position] if position < len(top.children) else None
            if node is not None and self.__own_root(node).root_id == root.root_id:
                self.__update_root(node, root)
                continue
            moved = next(
                (other for other in top.children[position + 1 :] if self.__own_root(other).root_id == root.root_id),
                None,
            )
            if moved is None:
                node = RootsFolderModel.Node(root.label, RootsNodeKind.ROOT, top, root=root)
                self.__insert(top, position, [node])
                self.__request(node)
            else:
                self.__move(top, moved.row, position)
                self.__update_root(moved, root)

    def __update_root(self, node: RootsFolderModel.Node, root: RehucoRoot) -> None:
        """Bring a shown root up to date with the file.

        :param node: the root's row.
        :param root: what the file says it is now.
        """
        current = self.__own_root(node)
        if current == root:
            return
        node.root = root
        node.name = root.label
        if current.path != root.path:
            self.__remove_children(node)
            node.listing = NodeListing.UNLISTED
            node.listed_at = None
            self.__request(node)
        self.__changed(node)

    def __own_root(self, node: RootsFolderModel.Node) -> RehucoRoot:
        """The root a row belongs to.

        :param node: a root row.
        :returns: its root.
        """
        return cast(RehucoRoot, node.root)  # only a root row is asked

    # endregion

    # region listing

    @override
    def canFetchMore(self, parent: ModelIndex) -> bool:  # noqa: N802  (Qt API name)
        node = self.__node(parent)
        return node.kind in LISTABLE_KINDS and node is not self.__top and node.listing is NodeListing.UNLISTED

    @override
    def fetchMore(self, parent: ModelIndex) -> None:  # noqa: N802  (Qt API name)
        node = self.__node(parent)
        if self.canFetchMore(parent):
            self.__request(node)

    def relist(self, index: ModelIndex, *, unless_listed_within: float | None = None) -> bool:
        """List a loaded root or folder again, in place.

        Rows already shown stay until the answer lands, and a folder never asked for is left to be fetched when a
        view first wants it.

        **A freshness window**, for a caller that asks on every visit (#487): a folder whose listing is still out, or
        landed less than ``unless_listed_within`` seconds ago by :func:`time.monotonic`, is shown as it is and not asked
        again. Nothing runs to enforce it -- the time of the last answer is compared at the next ask. A caller that
        must list again whatever came before (F5, a write the app made) gives no window.

        :param index: the root or folder.
        :param unless_listed_within: seconds a listing stays fresh, or ``None`` for none.
        :returns: whether a listing was started.
        """
        node = self.__node(index)
        if node is self.__top or node.kind not in LISTABLE_KINDS or node.listing is NodeListing.UNLISTED:
            return False
        if unless_listed_within is not None and (
            node.listing is NodeListing.PENDING
            or (node.listed_at is not None and time.monotonic() - node.listed_at < unless_listed_within)
        ):
            return False
        self.__request(node)
        return True

    def relist_chain(self, index: ModelIndex) -> None:
        """List again every loaded root and folder from ``index``'s own root down to ``index`` -- the columns on
        screen when ``index`` is current.

        :param index: any row.
        """
        node: RootsFolderModel.Node | None = self.__node(index)
        while node is not None and node is not self.__top:
            self.relist(self.__index_for(node))
            node = node.parent

    def relist_under(self, path: Path) -> None:
        """List again every loaded root and folder at or under ``path`` -- what a verify that rewrote a record covering
        a whole folder tree has made stale.

        :param path: the folder.
        """
        top = self.__find(path)
        pending = [] if top is None else [top]
        while pending:
            node = pending.pop()
            self.relist(self.__index_for(node))
            pending.extend(child for child in node.children if child.kind in LISTABLE_KINDS)

    def relist_folder(self, path: Path) -> None:
        """List again the folder at ``path`` if it is a loaded root or folder, for a folder the app changed.

        :param path: the folder.
        """
        node = self.__find(path)
        if node is not None:
            self.relist(self.__index_for(node))

    def __request(self, node: RootsFolderModel.Node) -> None:
        """Start listing a root or folder, dropping any earlier request for it.

        A folder with no rows yet gets a *Loading* row, so its column is never blank while the read is out.

        :param node: the root or folder.
        """
        lister = self.__lister
        if lister is None:
            return
        self.__pending.pop(node.request, None)
        serial = next(self.__serials)
        node.request = serial
        self.__pending[serial] = node  # pylint: disable=unsupported-assignment-operation
        node.listing = NodeListing.PENDING
        if not node.children:
            self.__insert(node, 0, [RootsFolderModel.Node(LOADING_ROW, RootsNodeKind.LOADING, node)])
        self.__loader.start(
            serial, lister, self.__root_above(node).root_id, self.__relative(node), self.__covering(node)
        )

    def __announce_records(self, node: RootsFolderModel.Node) -> None:
        """Say which records a folder bears on: those it shows, and the one above that manages it (#487).

        :param node: the root or folder, whose rows are the listing's.
        """
        folder = self.__root_above(node).path.joinpath(*self.__relative(node))
        records = [
            folder / child.name
            for child in node.children
            if child.kind is RootsNodeKind.FILE and is_record_name(child.name)
        ]
        above = self.__record_above(node)
        if above is not None:
            records.append(self.__root_above(node).path.joinpath(*above))
        self.records_listed.emit(folder, tuple(records))

    def __record_above(self, node: RootsFolderModel.Node) -> tuple[str, ...] | None:
        """The directory-scoped record above ``node`` that manages it, as a path under the root.

        Read from the listings the model already holds, like :meth:`__covering` -- which also wants a checksum file
        beside it, where this wants only the record. The nearest ancestor with one decides; ``info.rehu`` before
        ``info.tc``.

        :param node: the root or folder.
        :returns: the record's path under its root; ``None`` when no loaded ancestor holds one.
        """
        ancestor = node.parent
        while ancestor is not None and ancestor is not self.__top:
            names = {child.name for child in ancestor.children if child.kind is RootsNodeKind.FILE}
            record = next((name for name in DIRECTORY_SCOPED_FILENAMES if name in names), None)
            if record is not None:
                return (*self.__relative(ancestor), record)
            ancestor = ancestor.parent
        return None

    def __covering(self, node: RootsFolderModel.Node) -> tuple[str, ...] | None:
        """The directory-scoped record above ``node`` whose ``info.checksum`` covers it, as a path under the root.

        Read from the listings the model already holds, so it costs no disk read: the nearest ancestor with a
        directory-scoped record decides, and a record that has no ``info.checksum`` beside it covers nothing. An
        ``info.rehu`` is preferred over an ``info.tc`` a conversion left beside it.

        :param node: the root or folder about to be listed.
        :returns: the record's path under its root; ``None`` when no loaded ancestor is a resource with a checksum
            file.
        """
        ancestor = node.parent
        while ancestor is not None and ancestor is not self.__top:
            names = {child.name for child in ancestor.children if child.kind is RootsNodeKind.FILE}
            record = next((name for name in DIRECTORY_SCOPED_FILENAMES if name in names), None)
            if record is not None:
                if "info.checksum" not in {name.lower() for name in names}:
                    return None
                return (*self.__relative(ancestor), record)
            ancestor = ancestor.parent
        return None

    def __on_listed(self, serial: int, listing: DirectoryListing) -> None:
        """Show an answer, unless the row it was for has gone or asked again since.

        :param serial: the request's serial.
        :param listing: what the folder held.
        """
        node = self.__pending.pop(serial, None)
        if node is None or node.request != serial:
            return
        node.listed_at = time.monotonic()
        for row in reversed(range(len(node.children))):
            if node.children[row].kind in PLACEHOLDER_KINDS:
                self.__remove(node, row)
        if listing.reachable:
            self.__show_entries(node, listing)
            self.__announce_records(node)
        else:
            self.__remove_children(node)
            node.listing = NodeListing.UNREACHABLE
            offline = FOLDER_NOT_FOUND_ROW
            if node.kind is RootsNodeKind.ROOT:
                offline = ROOT_STORAGE_OFFLINE_ROWS[self.__own_root(node).storage]
            self.__insert(node, 0, [RootsFolderModel.Node(offline, RootsNodeKind.UNREACHABLE, node)])
        self.__changed(node)

    def __show_entries(self, node: RootsFolderModel.Node, listing: DirectoryListing) -> None:
        """Make ``node``'s rows the listing's, keeping every row it already shows that is still there.

        :param node: the listed root or folder.
        :param listing: what it holds, reachable.
        """
        entries = sorted(listing.entries, key=lambda entry: (not entry.is_directory, natural_sort_key(entry.name)))
        stale_after, now = shared_checksum_settings().stale_after, datetime.now(UTC)
        wanted = {entry.name: entry.is_directory for entry in entries}
        children = node.children
        for row in reversed(range(len(children))):
            child = children[row]
            if wanted.get(child.name) is None or wanted[child.name] != (child.kind is RootsNodeKind.FOLDER):
                self.__remove(node, row)
        position = 0
        fresh: list[RootsFolderModel.Node] = []
        for entry in entries:
            if position < len(node.children) and node.children[position].name == entry.name:  # pylint: disable=no-member
                if fresh:
                    self.__insert(node, position, fresh)
                    position += len(fresh)
                    fresh = []
                self.__update_row(node.children[position], entry, listing, stale_after, now)
                position += 1
            else:
                kind = RootsNodeKind.FOLDER if entry.is_directory else RootsNodeKind.FILE
                fresh.append(
                    RootsFolderModel.Node(
                        entry.name,
                        kind,
                        node,
                        entry.file_type,
                        size=entry.size,
                        modified=entry.modified,
                        checksum=row_checksum(listing.covered.get(entry.name), stale_after, now),
                        bookkeeping=entry.kind in BOOKKEEPING_KINDS,
                    )
                )
        if fresh:
            self.__insert(node, position, fresh)
        node.listing = NodeListing.LISTED

    def __update_row(
        self,
        child: RootsFolderModel.Node,
        entry: DirectoryEntry,
        listing: DirectoryListing,
        stale_after: timedelta,
        now: datetime,
    ) -> None:
        """Bring a row that is still listed up to date, announcing it only if something it shows changed.

        :param child: the row.
        :param entry: what the listing now says it is.
        :param listing: the whole listing, for what its covering record says.
        :param stale_after: how long a check stays fresh.
        :param now: the instant every file of the listing is aged against.
        """
        checksum = row_checksum(listing.covered.get(entry.name), stale_after, now)
        bookkeeping = entry.kind in BOOKKEEPING_KINDS
        current = (child.file_type, child.size, child.modified, child.checksum, child.bookkeeping)
        if current != (entry.file_type, entry.size, entry.modified, checksum, bookkeeping):
            child.file_type, child.size, child.modified = entry.file_type, entry.size, entry.modified
            child.checksum, child.bookkeeping = checksum, bookkeeping
            self.__changed(child)

    # endregion

    # region the app's own renames

    def relocate(self, relocation: Relocation) -> None:
        """Follow a rename the app carried out, reading nothing.

        A shown row renamed within its folder is renamed in place and moved to where its new name sorts, its loaded
        subtree following; one moved to another folder is removed, and the folder it arrived in is listed again if
        it is loaded. A rename of a root's own folder is not followed: the ``.rehuco`` still points at the old path,
        and the root says so by listing as unreachable.

        :param relocation: the rename's executed plan.
        """
        for source, destination in relocation.pairs:
            node = self.__find(source)
            if node is None or node.kind is RootsNodeKind.ROOT or node.parent is None:
                self.relist_folder(destination.parent)
                continue
            if Relocation.path_parts(source.parent) == Relocation.path_parts(destination.parent):
                node.name = destination.name
                self.__changed(node)
                self.__resort(node)
            else:
                self.__remove(node.parent, node.row)
                self.relist_folder(destination.parent)

    def __resort(self, node: RootsFolderModel.Node) -> None:
        """Move a renamed row to where its new name sorts among its siblings.

        :param node: the renamed folder or file.
        """
        parent = node.parent
        if parent is None:  # pragma: no cover  (a renamed row is never a root)
            return
        siblings = [child for child in parent.children if child is not node and child.kind not in PLACEHOLDER_KINDS]
        keys = [RootsFolderModel.__sort_key(child) for child in siblings]
        target = bisect_left(keys, RootsFolderModel.__sort_key(node))
        placeholders = len(parent.children) - len(siblings) - 1
        self.__move(parent, node.row, target + placeholders)

    @staticmethod
    def __sort_key(node: RootsFolderModel.Node) -> tuple[bool, tuple[Any, ...]]:
        """What orders folders before files, each in natural order.

        :param node: a folder or file.
        :returns: its sort key.
        """
        return node.kind is not RootsNodeKind.FOLDER, natural_sort_key(node.name)

    def __find(self, path: Path) -> RootsFolderModel.Node | None:
        """The loaded row for ``path``.

        :param path: an absolute path.
        :returns: the row, or ``None`` when no root holds it or some folder on the way is not loaded.
        """
        parts = Relocation.path_parts(path)
        for root_node in self.__top.children:
            root_parts = Relocation.path_parts(self.__own_root(root_node).path)
            if parts[: len(root_parts)] != root_parts:
                continue
            node: RootsFolderModel.Node | None = root_node
            for name in parts[len(root_parts) :]:
                node = next(
                    (
                        child
                        for child in node.children
                        if child.kind not in PLACEHOLDER_KINDS and os_path.normcase(child.name) == name
                    ),
                    None,
                )
                if node is None:
                    return None
            return node
        return None

    # endregion

    # region reading nodes

    def node_kind(self, index: ModelIndex) -> RootsNodeKind | None:
        """What the row at ``index`` is.

        :param index: any index.
        :returns: its kind, or ``None`` for an invalid index.
        """
        return self.__node(index).kind if index.isValid() else None

    def root_at(self, index: ModelIndex) -> RehucoRoot | None:
        """The root a **root row** stands for.

        :param index: any index.
        :returns: the root, or ``None`` unless ``index`` is a root row.
        """
        if not index.isValid():
            return None
        node = self.__node(index)
        return node.root if node.kind is RootsNodeKind.ROOT else None

    def root_of(self, index: ModelIndex) -> RehucoRoot | None:
        """The root a row is under, a root row's own included.

        :param index: any index.
        :returns: the root, or ``None`` for an invalid index.
        """
        return self.__root_above(self.__node(index)) if index.isValid() else None

    def key(self, index: ModelIndex) -> tuple[UUID, tuple[str, ...]] | None:
        """Where a root, folder or file is: the root's id and the names down to it -- the key the one listing
        function is asked by.

        :param index: any index.
        :returns: the key, or ``None`` for an invalid index or a placeholder.
        """
        if not index.isValid():
            return None
        node = self.__node(index)
        if node.kind in PLACEHOLDER_KINDS:
            return None
        return self.__root_above(node).root_id, self.__relative(node)

    def index_for(self, root_id: UUID, relative: tuple[str, ...]) -> QModelIndex:
        """The row at a key, or the deepest row on the way to it that exists.

        :param root_id: the root.
        :param relative: the names down from it.
        :returns: the row's index; invalid when the root is not shown.
        """
        node = next((root for root in self.__top.children if self.__own_root(root).root_id == root_id), None)
        if node is None:
            return QModelIndex()
        for name in relative:
            child = next((c for c in node.children if c.kind not in PLACEHOLDER_KINDS and c.name == name), None)
            if child is None:
                break
            node = child
        return self.__index_for(node)

    def file_type_of(self, index: ModelIndex) -> FileType | None:
        """What a folder or file is by shape.

        :param index: any index.
        :returns: its type, or ``None`` for an invalid index, a root or a placeholder.
        """
        if not index.isValid():
            return None
        node = self.__node(index)
        return None if node.root is not None or node.kind in PLACEHOLDER_KINDS else node.file_type

    def child_names(self, index: ModelIndex) -> tuple[str, ...] | None:
        """The names a listed root or folder holds, as the listing gave them.

        **A folder being listed again still answers** (#457): its rows stay until the answer lands, and a reader
        asked mid-relist (the pane rebuilding its buttons as a verify's rewrite is diffed in) must not hear "nothing".

        :param index: a root or folder.
        :returns: the names of its folders and files; ``None`` while nothing is known about what is in it -- never
            asked for, a first listing still out, or away.
        """
        if not index.isValid():
            return None
        node = self.__node(index)
        if node.listing not in (NodeListing.LISTED, NodeListing.PENDING):
            return None
        names = tuple(child.name for child in node.children if child.kind not in PLACEHOLDER_KINDS)
        if node.listing is NodeListing.PENDING and not names:
            return None
        return names

    def listing_state(self, index: ModelIndex) -> NodeListing | None:
        """Where a root's or folder's listing stands.

        :param index: any index.
        :returns: its state, or ``None`` for an invalid index.
        """
        return self.__node(index).listing if index.isValid() else None

    def path_of(self, index: ModelIndex) -> Path | None:
        """Where a root, folder or file is on disk.

        :param index: any index.
        :returns: its path, or ``None`` for an invalid index or a placeholder.
        """
        if not index.isValid() or self.__node(index).kind in PLACEHOLDER_KINDS:
            return None
        node = self.__node(index)
        return self.__root_above(node).path.joinpath(*self.__relative(node))

    def __node(self, index: ModelIndex) -> RootsFolderModel.Node:
        """The row behind an index.

        :param index: any index.
        :returns: its row; the invisible top for an invalid one.
        """
        return cast(RootsFolderModel.Node, index.internalPointer()) if index.isValid() else self.__top

    def __index_for(self, node: RootsFolderModel.Node) -> QModelIndex:
        """The index of a row.

        :param node: any row.
        :returns: its index; invalid for the top.
        """
        return QModelIndex() if node is self.__top else self.createIndex(node.row, 0, node)

    def __root_above(self, node: RootsFolderModel.Node) -> RehucoRoot:
        """The root a row is under.

        :param node: any row but the top.
        :returns: the root.
        """
        while node.parent is not None and node.parent is not self.__top:
            node = node.parent
        return self.__own_root(node)

    def __relative(self, node: RootsFolderModel.Node) -> tuple[str, ...]:
        """The names from a row's root down to it.

        :param node: any row but the top.
        :returns: the names; empty for a root.
        """
        names: list[str] = []
        while node.parent is not None and node.parent is not self.__top:
            names.append(node.name)
            node = node.parent
        return tuple(reversed(names))

    # endregion

    # region the model interface

    @override
    def index(self, row: int, column: int, parent: ModelIndex = QModelIndex()) -> QModelIndex:
        if column != 0 or row < 0:
            return QModelIndex()
        children = self.__node(parent).children
        return self.createIndex(row, 0, children[row]) if row < len(children) else QModelIndex()

    @override
    def parent(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, child: ModelIndex = QModelIndex()
    ) -> QModelIndex:
        if not child.isValid():
            return QModelIndex()
        above = self.__node(child).parent
        return QModelIndex() if above is None or above is self.__top else self.__index_for(above)

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return len(self.__node(parent).children)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        del parent
        return 1

    @override
    def hasChildren(self, parent: ModelIndex = QModelIndex()) -> bool:  # noqa: N802  (Qt API name)
        node = self.__node(parent)
        if node.kind not in LISTABLE_KINDS:
            return False
        if node is self.__top:
            return bool(node.children)
        return bool(node.children) or node.listing in (NodeListing.UNLISTED, NodeListing.PENDING)

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            # the list itself takes a drop: a root is placed between two others, never inside one
            return Qt.ItemFlag.ItemIsDropEnabled if self.__reorderable else Qt.ItemFlag.NoItemFlags
        node = self.__node(index)
        if node.kind in PLACEHOLDER_KINDS:
            return Qt.ItemFlag.ItemIsEnabled
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self.__reorderable and node.kind is RootsNodeKind.ROOT:
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        return flags

    def set_reorderable(self, reorderable: bool) -> None:
        """Say whether roots may be dragged to another place -- they may not while the file is read-only or none is
        open.

        :param reorderable: whether they may.
        """
        self.__reorderable = reorderable

    @override
    def supportedDropActions(self) -> Qt.DropAction:  # noqa: N802  (Qt API name)
        return Qt.DropAction.MoveAction

    @override
    def mimeTypes(self) -> list[str]:  # noqa: N802  (Qt API name)
        return [ROOT_MIME_TYPE]

    @override
    def mimeData(self, indexes: Sequence[QModelIndex]) -> QMimeData:  # noqa: N802  (Qt API name)
        data = QMimeData()
        root = next((root for root in map(self.root_at, indexes) if root is not None), None)
        if root is not None:
            data.setData(ROOT_MIME_TYPE, str(root.root_id).encode("ascii"))
        return data

    @override
    def dropMimeData(  # noqa: N802  (Qt API name)
        self, data: QMimeData, action: Qt.DropAction, row: int, column: int, parent: ModelIndex
    ) -> bool:
        """Ask for a dragged root to be put before ``row``, once it is dropped between two roots.

        :param data: what was dragged.
        :param action: what the drop asks for; only a move is taken.
        :param row: the row the root is dropped before, or ``-1`` for the end of the list.
        :param column: unused.
        :param parent: where it was dropped; anything but the list itself is refused.
        :returns: whether the drop was taken.
        """
        del column
        top = self.__top
        if (
            not self.__reorderable
            or action != Qt.DropAction.MoveAction
            or parent.isValid()
            or not data.hasFormat(ROOT_MIME_TYPE)
        ):
            return False
        try:
            root_id = UUID(bytes(data.data(ROOT_MIME_TYPE).data()).decode("ascii"))
        except ValueError:
            return False
        current = next((i for i, node in enumerate(top.children) if self.__own_root(node).root_id == root_id), None)
        if current is None:
            return False
        before = len(top.children) if row < 0 else row
        self.request_root_move(current, before - 1 if before > current else before)
        return True

    def request_root_move(self, row: int, to: int) -> bool:
        """Ask for the root at ``row`` to end up at ``to`` -- a dragged root dropped, or a drop on the view -- by
        :attr:`root_move_requested`; asked for nothing while roots cannot be reordered or when it is already there.

        :param row: the root's row.
        :param to: the row it should end up at, in the list as it will be.
        :returns: whether a move was asked for.
        """
        top = self.__top
        if not self.__reorderable or not 0 <= row < len(top.children) or to == row:
            return False
        self.root_move_requested.emit(self.__own_root(top.children[row]).root_id, to)
        return True

    @override
    # one return per role, the shape every model's ``data`` has
    # pylint: disable-next=too-many-return-statements,too-many-branches
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid():
            return None
        node = self.__node(index)
        root = node.root
        unreachable = node.listing is NodeListing.UNREACHABLE
        match role:
            case Qt.ItemDataRole.DisplayRole:
                return node.name
            case RootsFolderModel.ICON_PATH_ROLE:
                if root is not None:
                    return ROOT_STORAGE_ICONS[root.storage]
                return FILE_TYPE_ICONS[node.file_type] if node.kind not in PLACEHOLDER_KINDS else None
            case RootsFolderModel.PATH_ROLE:
                return None if root is None else str(root.path)
            case RootsFolderModel.SIZE_ROLE:
                return node.size
            case RootsFolderModel.MODIFIED_ROLE:
                return node.modified
            case RootsFolderModel.CHECKSUM_ROLE:
                return node.checksum
            case RootsFolderModel.BOOKKEEPING_ROLE:
                return node.bookkeeping
            case RootsFolderModel.GREYED_ROLE:
                return node.kind in PLACEHOLDER_KINDS or (
                    root is not None and unreachable and root.storage is not RootStorage.LOCAL
                )
            case Qt.ItemDataRole.FontRole:
                if root is not None and unreachable and root.storage is RootStorage.LOCAL:
                    font = QFont()
                    font.setStrikeOut(True)
                    return font
                return None
            case Qt.ItemDataRole.ToolTipRole:
                if root is None:
                    checksum = node.checksum
                    return None if checksum is None else checksum_tooltip_for(checksum.state, checksum.untrusted)
                tooltip = str(root.path)
                if unreachable:
                    tooltip += "\n" + ROOT_STORAGE_OFFLINE_TOOLTIPS[root.storage]
                return tooltip
        return None

    # endregion

    # region changing rows

    def __insert(self, parent: RootsFolderModel.Node, row: int, nodes: list[RootsFolderModel.Node]) -> None:
        """Insert rows.

        :param parent: the row to insert under.
        :param row: where the first goes.
        :param nodes: the rows, in order.
        """
        self.beginInsertRows(self.__index_for(parent), row, row + len(nodes) - 1)
        parent.children[row:row] = nodes  # pylint: disable=unsupported-assignment-operation
        RootsFolderModel.__renumber(parent, row)
        self.endInsertRows()

    def __remove(self, parent: RootsFolderModel.Node, row: int) -> None:
        """Remove one row, and with it everything under it.

        :param parent: the row it is under.
        :param row: its row.
        """
        self.beginRemoveRows(self.__index_for(parent), row, row)
        gone = parent.children.pop(row)
        RootsFolderModel.__renumber(parent, row)
        self.__forget(gone)
        self.__retire(gone)
        self.endRemoveRows()

    def __remove_children(self, parent: RootsFolderModel.Node) -> None:
        """Remove every row under a root or folder.

        :param parent: the root or folder.
        """
        if not parent.children:
            return
        self.beginRemoveRows(self.__index_for(parent), 0, len(parent.children) - 1)
        gone, parent.children = parent.children, []
        for node in gone:
            self.__forget(node)
            self.__retire(node)
        self.endRemoveRows()

    def __move(self, parent: RootsFolderModel.Node, row: int, target: int) -> None:
        """Move one row to where it will sit in the end.

        :param parent: the row they are under.
        :param row: where it is now.
        :param target: the row it ends up at.
        """
        if row == target:
            return
        index = self.__index_for(parent)
        # Qt names the row the move goes *before*, in the list as it is now
        if not self.beginMoveRows(index, row, row, index, target + 1 if target > row else target):
            return  # pragma: no cover  (only for a move that is not one)
        parent.children.insert(target, parent.children.pop(row))
        RootsFolderModel.__renumber(parent, min(row, target))
        self.endMoveRows()

    def __changed(self, node: RootsFolderModel.Node) -> None:
        """Say a row's data changed.

        :param node: the row.
        """
        index = self.__index_for(node)
        self.dataChanged.emit(index, index)

    @staticmethod
    def __renumber(parent: RootsFolderModel.Node, start: int) -> None:
        """Set the row of every child from ``start`` on.

        :param parent: the row whose children changed.
        :param start: the first child whose row may have changed.
        """
        for row in range(start, len(parent.children)):
            parent.children[row].row = row

    def __forget(self, node: RootsFolderModel.Node) -> None:
        """Drop the requests still out for a removed row and everything under it, so their answers are ignored.

        :param node: the removed row.
        """
        self.__pending.pop(node.request, None)
        node.request = 0
        for child in node.children:
            self.__forget(child)

    def __retire(self, node: RootsFolderModel.Node) -> None:
        """Keep a removed row alive until the event loop has turned.

        :param node: the removed row.
        """
        if not self.__retired:
            QTimer.singleShot(0, self, self.__release)
        self.__retired.append(node)

    def __release(self) -> None:
        """Let go of the removed rows."""
        self.__retired = []

    # endregion
