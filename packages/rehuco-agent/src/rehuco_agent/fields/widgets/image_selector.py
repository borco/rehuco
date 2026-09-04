"""The lightbox-curation editor: a sized preview above a checkable screenshot list ([[plugins#field-toolkit]], #27).

A two-pane **vertical** :class:`QSplitter` whose split position is persisted per ``.rehu`` (#72): on top a
preview of the selected item with its pixel dimensions in a bottom-right overlay; below it a
:class:`QTreeView` of *all* ``<stem>NN`` screenshot siblings, each checked by default and showing its
pixel dimensions and file size; unchecking one **hides** it from the lightbox. The UI is the inverse of
storage -- checked = visible, and only the hidden exceptions are emitted -- because checked-by-default
reads more naturally ([[data-model#image-meanings]]).
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, override

import humanize
from borco_pyside.core import SimpleProperty
from borco_pyside.widgets import ItemEditActionsColumn, ItemOrderingActionsColumn
from PIL import Image
from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QPixmap, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QTreeView,
    QWidget,
)

from ...item_action_icons import apply_action_column_icons
from ..image_organizer import ImageOrganizer
from ..image_scanner import ImageScanner

LOG: Final = logging.getLogger(__name__)

PATH_ROLE: Final = Qt.ItemDataRole.UserRole
"""The item-data role storing each list entry's screenshot :class:`~pathlib.Path`."""

NAME_COLUMN: Final = 0
DIMENSIONS_COLUMN: Final = 1
SIZE_COLUMN: Final = 2

PREVIEW_PANE: Final = 0
LIST_PANE: Final = 1
"""Which splitter pane is which -- the preview on top, the screenshot list under it (#72)."""

PREVIEW_HEIGHT: Final = 100
"""How tall the preview pane opens, in pixels, when its owner names no height (#72). The user's own
choice reaches this widget from the owner (the "Images" settings page); the number lives next to the widget it
sizes, and the settings section reads it from here as its default -- the same arrangement
:data:`~rehuco_agent.fields.images_field.IMAGE_STRIP_HEIGHT` already has with the strip."""


class PreviewLabel(QLabel):
    """A label that keeps a source pixmap scaled to fit itself, aspect-ratio preserved.

    Shared with the maximized viewer (`ImageLightbox`, #160), which needs exactly this discipline at a
    much larger size; it lives here because this is where it was first proven.

    Rescaling lives in the label's own :meth:`resizeEvent` rather than the surrounding widget's, so the
    first paint is correct no matter when the layout hands the label its real size -- there is no reliance
    on an outer resize firing after the pixmap is set. Its size policy ignores the pixmap so the pixmap
    never drives (and inflates) the layout.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__source = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def set_source(self, pixmap: QPixmap) -> None:
        """Adopt ``pixmap`` as the source to display, rescaled to the current size.

        :param pixmap: the full-resolution pixmap to show, or a null pixmap to clear.
        """
        self.__source = pixmap
        self.__rescale()

    def __rescale(self) -> None:
        """Repaint the source pixmap scaled to fit the label, or clear when there is none."""
        if self.__source.isNull():
            self.clear()
            return
        self.setPixmap(
            self.__source.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Rescale the source pixmap to the label's new size.

        :param event: the Qt resize event, forwarded to the base class.
        """
        super().resizeEvent(event)
        self.__rescale()

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """Rescale when the label is (re-)shown, e.g. a QtAds tab switched back into view.

        While a dock tab is hidden QtAds detaches its content, so the label never sees the resize to its
        real size; rescaling on show fixes up an otherwise-stale (tiny) first paint on selection.

        :param event: the Qt show event, forwarded to the base class.
        """
        super().showEvent(event)
        self.__rescale()


@dataclass
class ScreenshotRow:
    """One screenshot as the curation list holds it (#72).

    The metrics are read once, when the row is built, rather than on every repaint: they come off
    disk, and a view asks for a cell's data far more often than a file changes size.

    :ivar path: the screenshot itself; its filename is what the name column shows.
    :ivar hidden: whether it is curated out of the lightbox ([[data-model#image-meanings]]) -- the
        inverse of the check box, since storage records only the hidden exceptions.
    :ivar dimensions: its ``W x H`` pixel size, blank when unreadable.
    :ivar size: its humanized file size, blank when unreadable.
    """

    path: Path
    hidden: bool
    dimensions: str
    size: str


class ScreenshotListModel(QAbstractTableModel):
    """The curation list's rows: a resource's screenshots, owned outright (#72).

    A real model over a plain list, so every edit is reported as the thing it is --
    :meth:`move_row` brackets the reorder in ``beginMoveRows``/``endMoveRows`` and a view sees one
    ``rowsMoved``, keeping its scroll position, its selection and its persistent indexes; a delete is
    one ``rowsRemoved``; a rename is ``dataChanged`` on the rows whose files moved, leaving the
    dimensions and size columns alone because a rename moves a file's slot, not its bytes. Only a
    genuinely new set of screenshots resets.

    That the rows are owned here is what makes the move possible at all: ``beginMoveRows`` has to
    bracket the reordering of the model's *own* storage, which is a thing a list can do and a bag of
    item widgets cannot.

    Three columns: the filename (checkable -- checked means shown in the lightbox), the pixel
    dimensions, and the file size.

    :param parent: optional Qt parent.
    """

    HEADERS: Final = ("Name", "Dimensions", "Size")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__rows: list[ScreenshotRow] = []
        self.__organizer: ImageOrganizer | None = None

    def set_organizer(self, organizer: ImageOrganizer | None) -> None:
        """Adopt what renames this resource's screenshots on disk.

        Held by the model rather than by the widget above it, because rearranging the rows *is*
        renaming the files -- the two happen inside one transaction, so they cannot be owned in two
        places. ``None`` leaves the list read-only: a document with no path yet, or a legacy ``.tc``.

        :param organizer: the organizer to use, or ``None`` for a set nothing can rearrange.
        """
        self.__organizer = organizer

    @property
    def can_rearrange(self) -> bool:
        """Whether this resource's screenshots can be moved and deleted at all."""
        return self.__organizer is not None

    # region the model interface

    @override
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        """How many screenshots there are.

        :param parent: the parent index; a flat model has rows only at the root.
        :returns: the screenshot count, or ``0`` under any row.
        """
        return 0 if parent.isValid() else len(self.__rows)

    @override
    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        """How many columns each screenshot shows.

        :param parent: the parent index; a flat model has columns only at the root.
        :returns: the column count, or ``0`` under any row.
        """
        return 0 if parent.isValid() else len(self.HEADERS)

    @override
    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """The value of one cell in one role.

        :param index: the cell asked about.
        :param role: what about it is being asked for.
        :returns: the cell's value, or ``None`` when this model has nothing for that role.
        """
        row = self.__row(index)
        if row is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return (row.path.name, row.dimensions, row.size)[index.column()]
        if role == PATH_ROLE and index.column() == NAME_COLUMN:
            return row.path
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == NAME_COLUMN:
            # the UI is the inverse of storage: checked = visible ([[data-model#image-meanings]])
            return Qt.CheckState.Unchecked if row.hidden else Qt.CheckState.Checked
        return None

    @override
    def setData(
        self, index: QModelIndex | QPersistentModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole
    ) -> bool:
        """Curate one screenshot in or out of the lightbox.

        The check box is the only thing a user edits here -- a screenshot's name is its position in
        the set, not text to type -- so every other role is refused.

        :param index: the cell being set.
        :param value: the new check state.
        :param role: which role is being set.
        :returns: whether anything changed.
        """
        row = self.__row(index)
        if row is None or role != Qt.ItemDataRole.CheckStateRole or index.column() != NAME_COLUMN:
            return False
        hidden = Qt.CheckState(value) == Qt.CheckState.Unchecked
        if hidden == row.hidden:
            return False
        row.hidden = hidden
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    @override
    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        """What can be done with one cell.

        The name column is checkable; nothing is editable, since there is no text here a user writes
        -- a screenshot's name is its position in the set, which the move buttons decide.

        :param index: the cell asked about.
        :returns: its flags.
        """
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == NAME_COLUMN:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    @override
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """One column's title.

        :param section: the column (or row) asked about.
        :param orientation: which header is asking.
        :param role: what about it is being asked for.
        :returns: the column's title, or ``None`` -- the rows are files, so their numbers say nothing.
        """
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.HEADERS[section] if 0 <= section < len(self.HEADERS) else None

    # endregion

    def paths(self) -> list[Path]:
        """Every screenshot, in the order the rows are in.

        :returns: the paths, curated-out ones included -- hiding a screenshot from the lightbox does
            not take it out of the resource, so it still holds a slot in the numbering.
        """
        return [row.path for row in self.__rows]

    def hidden_filenames(self) -> list[str]:
        """The filenames of every screenshot curated out of the lightbox, in row order.

        :returns: the hidden filenames.
        """
        return [row.path.name for row in self.__rows if row.hidden]

    def set_rows(self, paths: list[Path], hidden: list[str]) -> None:
        """Replace every row, reading each screenshot's metrics off disk.

        A reset, because it genuinely is one: a different set of screenshots, not a rearrangement of
        this one. Every other edit here reports itself more precisely.

        :param paths: every screenshot sibling, in display order.
        :param hidden: the filenames to leave unchecked.
        """
        hidden_names = set(hidden)
        self.beginResetModel()
        try:
            self.__rows = [ScreenshotRow(path, path.name in hidden_names, *self.metrics(path)) for path in paths]
        finally:
            self.endResetModel()

    def move_row(self, source: int, target: int) -> bool:
        """Move one screenshot to ``target``, renaming the files inside the same transaction.

        The rename runs **between** ``beginMoveRows`` and ``endMoveRows``, because the rows and the
        files they stand for are one thing: a resource's screenshot order *is* its ``<stem>NN``
        numbering, so a row that has moved and a file that has not are not two states worth having.
        Doing the disk work inside the pair is what makes the whole rearrangement a single reported
        change, with no instant in between where a view could read the rows and the directory
        disagreeing.

        :param source: the row to move.
        :param target: the row it should end up at.
        :returns: whether the move happened.
        :raises OSError: if the rename failed; the rows are left as they were, and the caller is
            expected to reseed from disk -- the move has been reported by then, so the model's own
            account of itself is only trustworthy again after a reset.
        """
        if self.__organizer is None or source == target:
            return False
        if not 0 <= source < len(self.__rows) or not 0 <= target < len(self.__rows):
            return False
        # beginMoveRows names the position the row lands *before*, counted with the row still in
        # place -- so moving down is one past the row wanted, while moving up is the row itself
        destination = target + 1 if target > source else target
        # pragma-excluded, not omitted: Qt refuses a destination inside the moved span, which the
        # range guards above have already ruled out -- but an unbalanced begin without its end is bad
        # enough that the contract is worth honouring rather than assumed away
        if not self.beginMoveRows(QModelIndex(), source, source, QModelIndex(), destination):  # pragma: no cover
            return False
        try:
            ordered = list(self.__rows)
            ordered.insert(target, ordered.pop(source))
            renamed = self.__relabelled(ordered, self.__organizer.reorder([row.path for row in ordered]))
            self.__rows = ordered
        finally:
            self.endMoveRows()
        self.__report(renamed)
        return True

    def remove_row(self, row: int) -> bool:
        """Delete one screenshot, closing the gap it leaves, inside the same transaction.

        The unlink and the renumbering that follows it both run between ``beginRemoveRows`` and
        ``endRemoveRows``, for the reason :meth:`move_row` spells out.

        :param row: the row to delete.
        :returns: whether it was deleted.
        :raises OSError: if the delete or the renumbering failed; see :meth:`move_row`.
        """
        if self.__organizer is None or not 0 <= row < len(self.__rows):
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        try:
            remaining = self.__rows[:row] + self.__rows[row + 1 :]
            renames = self.__organizer.remove(self.__rows[row].path, [screenshot.path for screenshot in remaining])
            renamed = self.__relabelled(remaining, renames)
            self.__rows = remaining
        finally:
            self.endRemoveRows()
        self.__report(renamed)
        return True

    @staticmethod
    def __relabelled(rows: list[ScreenshotRow], renames: Mapping[str, str]) -> list[int]:
        """Point each renamed row at the file it is now.

        :param rows: the rows in the order they will be in, which is the order the names describe.
        :param renames: ``{old filename: new filename}``, as an `ImageOrganizer` reports.
        :returns: the positions in ``rows`` that changed.
        """
        changed = []
        for position, row in enumerate(rows):
            new_name = renames.get(row.path.name)
            if new_name is None:
                continue
            row.path = row.path.with_name(new_name)
            changed.append(position)
        return changed

    def __report(self, renamed: list[int]) -> None:
        """Repaint the rows a rename relabelled, once the structural change is complete.

        Emitted after the ``end...Rows`` rather than inside it: a row that merely changed *name* is
        not part of the move, and a view told about it mid-transaction is being asked to read a model
        that is still rearranging itself. Sent as one span rather than one signal per row -- a rename
        walks a contiguous run of slots, so the span is what actually changed either way.

        :param renamed: the positions that were relabelled.
        """
        if not renamed:
            return
        self.dataChanged.emit(
            self.index(min(renamed), NAME_COLUMN),
            self.index(max(renamed), NAME_COLUMN),
            [Qt.ItemDataRole.DisplayRole, PATH_ROLE],
        )

    def __row(self, index: QModelIndex | QPersistentModelIndex) -> ScreenshotRow | None:
        """The screenshot one index names.

        :param index: the index to resolve.
        :returns: its row, or ``None`` when the index names none.
        """
        if not index.isValid() or not 0 <= index.row() < len(self.__rows):
            return None
        return self.__rows[index.row()]

    @staticmethod
    def metrics(path: Path) -> tuple[str, str]:
        """The ``W x H`` pixel dimensions and humanized file size for ``path``, read from disk.

        Dimensions come from :class:`PIL.Image.Image.size`, a lazy header-only read for these formats
        -- the same convention already used by ``rehuco_core``'s legacy-screenshot slot-winner scoring
        (``rehuco_core.tc_screenshots``) -- far cheaper than the full-decode
        :class:`QPixmap` load the preview pane uses for the single selected image, and worthwhile here
        since every row needs it. Either value blanks out (rather than raising) when the file is
        missing or unreadable, e.g. an offline mount ([[mounts-and-storage#offline-mounts]]).

        :param path: the screenshot to inspect.
        :returns: the dimensions and humanized-size text, each blank when unavailable.
        """
        try:
            with Image.open(path) as image:
                width, height = image.size
            file_size = path.stat().st_size
        except OSError:
            return "", ""
        return f"{width} x {height}", humanize.naturalsize(file_size, gnu=True) if file_size else ""


class ScreenshotOrdering(QObject):
    """Adapts a screenshot list to the item-list toolkit's editor protocols ([[plugins#field-toolkit]], #72).

    The two action columns (`ItemEditActionsColumn`, `ItemOrderingActionsColumn`) drive an
    `ItemEditor` and an `ItemOrderingEditor`, and this is the thin piece that lets a *screenshot* list
    be one -- so the curation editor gets the same buttons, keys and enabled-state rules the settings
    pages' string lists and the ``authors`` rows already have, rather than a second set that behaves
    almost like them.

    Two of `ItemEditor`'s three calls have no meaning for screenshots and answer as no-ops: a
    screenshot is a file on disk, so there is no blank one to insert and no default set to restore.
    Their buttons are hidden by the selector and their keys never armed, so the no-ops are the
    protocol being satisfied rather than behavior anyone can reach.

    :param selector: the editor whose screenshots are moved and deleted; also the `ItemViewer` the
        columns read the current row from.
    """

    count_changed = Signal()
    """Fires whenever the number of screenshots changes -- what an ordering column reads to know
    whether the current row is at either end."""

    def __init__(self, selector: ImageSelector) -> None:
        super().__init__(selector)
        self.__selector: Final = selector
        selector.screenshots_changed.connect(self.count_changed)

    @property
    def count(self) -> int:
        """How many screenshots the list is showing."""
        return self.__selector.screenshot_count

    def insert(self, at: int) -> int:
        """No-op: there is no blank screenshot to add (see the class docstring).

        :param at: the row an insert would have gone after.
        :returns: ``at``, leaving the current row exactly where it was.
        """
        return at

    def reset(self) -> None:
        """No-op: a resource has no default set of screenshots to restore (see the class docstring)."""

    def delete(self, at: int) -> None:
        """Delete one screenshot from disk and close the gap it leaves.

        :param at: the row to delete.
        """
        self.__selector.delete_screenshot(at)

    def move_to_top(self, at: int) -> int:
        """Move one screenshot to the first slot.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__selector.move_screenshot(at, 0)

    def move_up(self, at: int) -> int:
        """Move one screenshot up a slot.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__selector.move_screenshot(at, at - 1)

    def move_down(self, at: int) -> int:
        """Move one screenshot down a slot.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__selector.move_screenshot(at, at + 1)

    def move_to_bottom(self, at: int) -> int:
        """Move one screenshot to the last slot.

        :param at: the row to move.
        :returns: the row it ended up at.
        """
        return self.__selector.move_screenshot(at, self.count - 1)


class ImageSelector(QSplitter):  # pylint: disable=too-many-instance-attributes
    """A sized preview above a checkable screenshot list ([[plugins#field-toolkit]], #27).

    Top pane -- the selected screenshot scaled to fit, with a ``W x H`` pixel-dimension overlay pinned
    bottom-right. Bottom pane -- every screenshot as a checkable row (checked = shown in the lightbox),
    with its pixel dimensions and file size read from disk into two further columns; toggling a row
    re-emits :attr:`hidden_changed` with the current hidden filenames. Where the two meet is this
    widget's own persisted state (`StatefulWidget`, #72) -- saved per ``.rehu`` with the document's
    dock layout, the same way the ``path`` editor's expand state is. A document with none remembered
    yet opens at the configured ``preview_height`` instead. The preview pane answers the app-wide
    previews toggle (``Ctrl+Shift+``, backtick, #71) alongside every document's strip, folding away
    to leave the curation list on its own.

    Holds its own :attr:`image_scanner`, so it can re-fetch its screenshots and rebuild itself whenever
    that changes (e.g. a `.tc` -> `.rehu` conversion switching naming conventions,
    [[acquisition-tooling#tc-to-rehu]]) without its owner having to push a fresh file list explicitly.

    :param parent: optional Qt parent.
    :param preview_height: the preview pane's pixel height on a document with no split remembered;
        the owner passes the user's configured height, and :data:`PREVIEW_HEIGHT` stands in when it
        names none.
    """

    hidden_changed = Signal(list)
    """Fires with the current list of hidden screenshot filenames whenever a row is checked/unchecked."""

    screenshots_changed = Signal()
    """Fires whenever the rows are rebuilt -- a curation edit, a scanner swap, or a rearrangement this
    editor just made on disk. The owner's cue that the *files* may have moved, which nothing else can
    tell a viewer built over the same directory (#72)."""

    current_index_changed = Signal()
    """Fires whenever :attr:`current_index` changes -- the `ItemViewer` contract the two action
    columns read to know which screenshot they act on."""

    image_scanner = SimpleProperty[ImageScanner | None](None)
    """The strategy resolving this resource's screenshots; ``None`` shows nothing."""

    image_organizer = SimpleProperty[ImageOrganizer | None](None)
    """What rearranges the screenshots on disk; ``None`` leaves this a read-only curation list, with
    the move and delete buttons disabled (a document with no path yet, or a legacy ``.tc``)."""

    def __init__(self, parent: QWidget | None = None, preview_height: int = PREVIEW_HEIGHT) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self.__preview_height = preview_height
        # the split still owes the preview its height -- cleared by whichever of a restore or a first
        # show gets there first, so a document's own remembered split is never overwritten by the default
        self.__pending_split = True
        self.__previews_visible = True
        # the split as it stood when the preview was toggled away, held until it comes back (#71)
        self.__stashed_state: bytes | None = None

        self.__preview_pane: Final = QWidget()
        overlay = QGridLayout(self.__preview_pane)
        overlay.setContentsMargins(0, 0, 0, 0)
        self.__preview: Final = PreviewLabel()
        self.__size_overlay: Final = QLabel()
        self.__size_overlay.setStyleSheet("background: rgba(0, 0, 0, 0.5); color: white; padding: 2px 6px;")
        self.__size_overlay.hide()
        overlay.addWidget(self.__preview, 0, 0)
        overlay.addWidget(self.__size_overlay, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.addWidget(self.__preview_pane)

        self.__list_model: Final = ScreenshotListModel(self)
        self.__list: Final = QTreeView()
        self.__list.setModel(self.__list_model)
        self.__list.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.__list.setRootIsDecorated(False)
        self.__list.setUniformRowHeights(True)
        self.__list.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        # a row is one file, and every action here acts on one: a multi-select would promise a bulk
        # move or delete that neither the buttons nor the rename plan behind them can carry out
        self.__list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.__list.header().setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        self.__list.header().setSectionResizeMode(DIMENSIONS_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        self.__list.header().setSectionResizeMode(SIZE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        self.__ordering: Final = ScreenshotOrdering(self)
        # the two ignores are the ones `ItemListEditor` needs for the same reason: PySide types a
        # class-level ``Signal`` as ``Signal``, not as the ``SignalInstance`` an *instance* exposes,
        # so neither this widget nor the ordering satisfies its protocol statically despite doing so
        self.__item_actions: Final = ItemEditActionsColumn(self.__ordering, self)  # type: ignore[arg-type]
        self.__ordering_actions: Final = ItemOrderingActionsColumn(self.__ordering, self)  # type: ignore[arg-type]
        # Insert, Edit and Reset ship with the edit column but mean nothing for a file on disk:
        # hidden outright rather than left disabled, since there is no state in which they would
        # become available. Their keys are never armed either -- only the actions added to the list
        # below have one, which is what stops Ins and F2 reaching the no-ops behind them.
        for unavailable in (
            self.__item_actions.insert_action,
            self.__item_actions.edit_action,
            self.__item_actions.reset_action,
        ):
            unavailable.setVisible(False)
        for action in (self.__item_actions.delete_action, *self.__ordering_action_list()):
            self.__list.addAction(action)
        # the same glyphs every other list editor in the app wears, from the one place naming them
        apply_action_column_icons(self.__ordering_actions, self.__item_actions)

        list_pane = QWidget()
        row = QHBoxLayout(list_pane)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.__list, 1)
        # ordering first, so the column that moves the row the buttons point at sits against the list
        row.addWidget(self.__ordering_actions)
        row.addWidget(self.__item_actions)
        for column in (self.__ordering_actions, self.__item_actions):
            # the columns are button-sized and the list fills the pane, so a centred column would
            # float its first button somewhere down the middle of the screenshots
            row.setAlignment(column, Qt.AlignmentFlag.AlignTop)
        self.addWidget(list_pane)

        # the list takes every pixel a resize hands out, so the preview keeps the height it was given:
        # a configured height that grew along with the dock would not be a configured height at all.
        # The height itself is applied on first show (:meth:`showEvent`), not here -- a splitter that
        # has never been laid out has no room to share out yet.
        self.setStretchFactor(PREVIEW_PANE, 0)
        self.setStretchFactor(LIST_PANE, 1)

        self.__list_model.dataChanged.connect(self.__on_data_changed)
        self.__list.selectionModel().currentChanged.connect(self.__on_current_changed)
        self.image_scanner_changed.connect(lambda _scanner: self.__refresh())  # type: ignore[attr-defined]
        self.image_organizer_changed.connect(lambda _organizer: self.__apply_organizer())  # type: ignore[attr-defined]
        self.__apply_organizer()

    def set_hidden(self, hidden: list[str]) -> None:
        """Resync the checked/unchecked rows from ``hidden``, rebuilding from the current scanner.

        Skips a redundant rebuild when ``hidden`` already matches what's shown -- the echo of this
        selector's *own* toggle coming back through the model binding.

        :param hidden: the filenames to leave unchecked.
        """
        if hidden == self.hidden_filenames():
            return
        self.__rebuild(hidden)

    # region rearranging the screenshots on disk (#72)

    @property
    def screenshot_count(self) -> int:
        """How many screenshots the list is showing."""
        return self.__list_model.rowCount()

    def screenshot_paths(self) -> list[Path]:
        """Every screenshot shown, in the order the rows are in.

        :returns: the paths, curated-out ones included -- hiding a screenshot from the lightbox does
            not take it out of the resource, so it still holds a slot in the numbering.
        """
        return self.__list_model.paths()

    def move_screenshot(self, at: int, to: int) -> int:
        """Move one screenshot to row ``to``, renaming the files so the disk agrees (#72).

        A resource's screenshot order **is** its ``<stem>NN`` numbering, so a move is a rename: the
        two files trade slot numbers, keeping their own extensions. Nothing is written to the
        document -- there is no stored order for it to disagree with.

        :param at: the row to move.
        :param to: the row it should end up at.
        :returns: the row it actually ended up at -- ``at`` when the move was out of range, refused
            (no organizer), or failed on disk.
        """
        return to if self.__rearranged(lambda: self.__list_model.move_row(at, to)) else at

    def delete_screenshot(self, at: int) -> None:
        """Delete one screenshot from disk, closing the gap it leaves (#72).

        Confirmed first: this unlinks a file and renumbers its neighbours, and neither half is
        something a document Revert can undo -- unlike every other edit this editor makes, which sit
        in the model until a Save. The row that took its place is left current, so deleting several
        in a row does not send the selection back to the top each time.

        :param at: the row to delete; out of range, or with no organizer, is a no-op.
        """
        paths = self.screenshot_paths()
        if not self.__list_model.can_rearrange or not 0 <= at < len(paths):
            return
        if not self.__confirmed_delete(paths[at]):
            return
        if self.__rearranged(lambda: self.__list_model.remove_row(at)):
            self.set_current_index(min(at, len(paths) - 2))

    def __confirmed_delete(self, path: Path) -> bool:
        """Ask before unlinking ``path``.

        :param path: the screenshot about to be deleted.
        :returns: whether the user confirmed.
        """
        answer = QMessageBox.question(
            self,
            "Delete screenshot",
            f"Delete <b>{path.name}</b> from this resource?<br><br>"
            "The file is removed from disk and the screenshots after it are renumbered to close the "
            "gap. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def __rearranged(self, rearrange: Callable[[], bool]) -> bool:
        """Run one of the model's rearrangements and report what it changed.

        The rows and the files move together inside the model's own transaction, so there is nothing
        to coordinate here -- only what the *document* has to hear about afterwards. The hidden set
        is filenames ([[data-model#image-meanings]]), and the model's relabelling is what carries it
        across a rename; the result is reported only when the **set** actually changed, since a pure
        reorder of two already-hidden screenshots would otherwise mark the document dirty with a
        value it already holds.

        :param rearrange: the model call to make.
        :returns: whether it happened.
        """
        hidden = self.hidden_filenames()
        try:
            rearranged = rearrange()
        except OSError:
            LOG.exception("could not rearrange this resource's screenshots")
            # reseeded from disk: the core's rollback is best effort, so the directory is the only
            # trustworthy account of the order now -- and the model reported a change it then failed
            # to make, so a reset is also what puts the view back on solid ground
            self.__rebuild(hidden)
            return False
        if not rearranged:
            return False
        remapped = self.hidden_filenames()
        if set(remapped) != set(hidden):
            self.hidden_changed.emit(remapped)
        self.screenshots_changed.emit()
        return True

    def __apply_organizer(self) -> None:
        """Hand the organizer to the model, and grey the buttons out when there is none.

        The model is where it lives, because rearranging the rows *is* renaming the files -- this
        widget only mirrors the answer into its buttons. They are disabled rather than hidden: a
        document with no path yet gets one the moment it is saved, and a list whose buttons come and
        go reads as a different editor each time.
        """
        self.__list_model.set_organizer(self.image_organizer)
        available = self.__list_model.can_rearrange
        self.__ordering_actions.setEnabled(available)
        self.__item_actions.setEnabled(available)

    def __ordering_action_list(self) -> tuple[QAction, ...]:
        """The ordering column's four actions, in column order.

        :returns: top, up, down, bottom.
        """
        return (
            self.__ordering_actions.move_to_top_action,
            self.__ordering_actions.move_up_action,
            self.__ordering_actions.move_down_action,
            self.__ordering_actions.move_to_bottom_action,
        )

    # endregion

    # region ItemViewer

    @property
    def current_index(self) -> int:
        """The row the two action columns act on; ``-1`` when there is none."""
        return self.__list.currentIndex().row()

    def set_current_index(self, row: int) -> None:
        """Make ``row`` the current one.

        :param row: the row to select, or a negative row to select none.
        """
        index = self.__list_model.index(row, NAME_COLUMN) if row >= 0 else QModelIndex()
        self.__list.setCurrentIndex(index)

    def edit_current(self) -> None:
        """No-op: a screenshot's name is its position in the set, not something typed into a row."""

    # endregion

    def set_previews_visible(self, visible: bool) -> None:
        """Fold the preview pane away, or bring it back, with the app-wide previews toggle (#71, #72).

        The editor answers the same ``Ctrl+Shift+`` (backtick) toggle every document's strip does, so
        one keystroke clears screenshots off screen everywhere rather than everywhere-but-here -- and
        what is left is exactly the curation list, which is the half of this editor that is not a
        screenshot.

        The split is **held, not lost**: hiding a splitter's child collapses it to nothing, so the
        state as it stood is stashed and re-applied when the pane returns, rather than the user coming
        back to a preview squeezed to zero. A selector that was toggled away before it was ever laid
        out has no split worth keeping, and falls back to the configured height.

        :param visible: whether the preview pane is shown.
        """
        if visible == self.__previews_visible:
            return
        self.__previews_visible = visible
        if not visible:
            self.__stashed_state = bytes(self.saveState().data()) if self.isVisible() else None
            self.__preview_pane.hide()
            return
        self.__preview_pane.show()
        stashed, self.__stashed_state = self.__stashed_state, None
        if stashed is None or not self.restoreState(QByteArray(stashed)):
            self.__apply_preview_height()

    def set_preview_height(self, height: int) -> None:
        """Re-split so the preview pane is ``height`` pixels tall (#72).

        Lets an already-built selector follow the user's configured height the moment they apply it,
        rather than only on the next document opened -- the same live-apply
        :meth:`~rehuco_agent.fields.widgets.image_strip.ImageStrip.set_height` gives the strip. An
        applied setting deliberately overrides a split the user had dragged: applying is the more
        recent of the two statements, and the dragged split is what a *later* drag restores.

        :param height: the pixel height the preview pane takes; the list keeps the rest.
        """
        if height == self.__preview_height:
            return
        self.__preview_height = height
        # folded away by the previews toggle: the new height is what the pane comes back at, so the
        # split held from before it hid is no longer the answer (#71)
        if not self.__previews_visible:
            self.__stashed_state = None
            return
        # a hidden selector has no room to divide (a QtAds tab behind another has none at all), so
        # the new height waits for the show that gives it one
        if self.isVisible():
            self.__apply_preview_height()
        else:
            self.__pending_split = True

    def __apply_preview_height(self) -> None:
        """Give the preview pane its configured height and the list everything left over."""
        room = self.height() - self.handleWidth() * (self.count() - 1)
        self.setSizes([self.__preview_height, max(0, room - self.__preview_height)])

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """Settle a split that is still owed its height, now that there is room to divide.

        :param event: the Qt show event, forwarded to the base class.
        """
        super().showEvent(event)
        if self.__pending_split:
            self.__pending_split = False
            self.__apply_preview_height()

    def save_state(self) -> bytes:
        """Encode where the preview/list split sits, for per-``.rehu`` session persistence
        (:class:`~rehuco_agent.fields.field.StatefulWidget`, #72).

        `QSplitter.saveState` rather than the raw :meth:`~PySide6.QtWidgets.QSplitter.sizes` list: it
        is what survives the pane being resized between the save and the restore, which is precisely
        what happens when a document reopens into a differently-sized dock.

        :returns: the splitter state blob, restorable by :meth:`restore_state`.
        """
        # while the preview is toggled away the live state describes a collapsed pane, which is the
        # toggle's doing and not the user's split -- so the stash is the honest answer, and saving
        # with previews off never costs a document the split it will come back to (#71)
        if self.__stashed_state is not None:
            return self.__stashed_state
        return bytes(self.saveState().data())

    def restore_state(self, state: bytes) -> None:
        """Restore the split position produced by :meth:`save_state`.

        :param state: the blob to restore from; anything Qt does not recognize (an empty blob, one
            written by an incompatible build) leaves the configured preview height to settle it, since
            `QSplitter.restoreState` refuses it and reports so rather than raising.
        """
        # a document restored while previews are toggled off has a split but nowhere to put it yet:
        # held in the stash, it is what the pane opens at when the toggle brings it back (#71)
        if not self.__previews_visible:
            self.__stashed_state = state
            self.__pending_split = False
            return
        # only a state Qt actually took settles the split: a refused blob leaves the document with no
        # remembered split at all, which is exactly the case the configured height is the answer to
        if self.restoreState(QByteArray(state)):
            self.__pending_split = False

    def __refresh(self) -> None:
        """Rebuild unconditionally -- the scanner changed, so even an unchanged hidden list needs a resync."""
        self.__rebuild(self.hidden_filenames())

    def __rebuild(self, hidden: list[str]) -> None:
        """Rebuild the list from the current scanner's screenshots.

        :param hidden: the filenames to leave unchecked.
        """
        scanner = self.image_scanner
        files = list(scanner.files()) if scanner is not None else []
        self.set_images(files, hidden)

    def set_images(self, paths: list[Path], hidden: list[str]) -> None:
        """Show ``paths``, checking each one not named in ``hidden``.

        A model reset, because it genuinely is one -- a different set of screenshots, rather than a
        rearrangement of this one, which reports itself far more precisely. Selects the first row so
        the preview is not blank when there are images.

        :param paths: every screenshot sibling, in display order.
        :param hidden: the filenames to leave *unchecked* (curated out of the lightbox).
        """
        self.__list_model.set_rows(paths, hidden)
        if self.__list_model.rowCount():
            self.__list.setCurrentIndex(self.__list_model.index(0, NAME_COLUMN))
        else:
            self.__show_preview(QPixmap())
        # every rebuild, not only the ones this editor caused: the owner cannot tell a rearrangement
        # from a scanner swap, and both mean a viewer over the same directory is now showing stale
        # filenames. It is also what re-reads the count the move buttons gate on (#72).
        self.screenshots_changed.emit()

    def hidden_filenames(self) -> list[str]:
        """The filenames of every currently-unchecked (hidden-from-lightbox) row, in list order.

        :returns: the hidden screenshot filenames.
        """
        return self.__list_model.hidden_filenames()

    def __on_data_changed(
        self, _top_left: QModelIndex, _bottom_right: QModelIndex, roles: list[int] | None = None
    ) -> None:
        """Re-emit :attr:`hidden_changed` when a row's check box changed, and only then.

        The role is what tells a *user* curating a screenshot apart from this widget relabelling a
        row after a rename -- both are data changes on the same rows, and only the first is an edit
        to report. Seeding needs no guard at all: it resets the model, which is not a data change.

        :param _top_left: the first cell that changed (unused -- the full list is recomputed).
        :param _bottom_right: the last cell that changed (unused).
        :param roles: what changed about them; an empty list means "everything", which no emitter
            here sends but which a defensive reader treats as including the check state.
        """
        if roles and Qt.ItemDataRole.CheckStateRole not in roles:
            return
        self.hidden_changed.emit(self.hidden_filenames())

    def __on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Load and preview the newly-selected screenshot.

        :param current: the newly-selected list index, in any column -- the path lives only on the
            row's name-column item, since selecting the row can land on any column.
        :param _previous: the previously-selected index (unused).
        """
        path = self.__list_model.index(current.row(), NAME_COLUMN).data(PATH_ROLE) if current.isValid() else None
        self.__show_preview(QPixmap(str(path)) if isinstance(path, Path) else QPixmap())
        self.current_index_changed.emit()

    def __show_preview(self, pixmap: QPixmap) -> None:
        """Adopt ``pixmap`` as the preview and refresh the size overlay.

        :param pixmap: the full-resolution screenshot to preview, or a null pixmap to clear.
        """
        self.__preview.set_source(pixmap)
        if pixmap.isNull():
            self.__size_overlay.hide()
        else:
            self.__size_overlay.setText(f"{pixmap.width()} x {pixmap.height()}")
            self.__size_overlay.show()
