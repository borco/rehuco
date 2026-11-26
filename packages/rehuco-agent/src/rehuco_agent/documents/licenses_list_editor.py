"""The License dock's list of a record's licenses: read while the dock reads, and added to, deleted from, retyped and
reordered by a grip while it edits ([[assets#licenses]], #705)."""

from typing import Final, cast, override

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor, ReorderDrag, RowBandDelegate, paint_drag_ghost
from borco_pyside.widgets.row_band_delegate import ModelIndex
from PySide6.QtCore import QAbstractItemModel, QMimeData, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)
from rehuco_core import ASSET_LICENSES, AssetLicense, LicenseTerms

from ..fields.widgets.editable_choice_combo_box import EditableChoiceComboBox
from ..grip_reorder import GRIP_WIDTH, GripReorderFilter, paint_grip
from ..item_action_icons import apply_item_action_icons
from .license_text_reader import LicenseTextReader
from .licenses_table_model import (
    LICENSE_COLUMN,
    LICENSE_MIME_TYPE,
    LicensesTableModel,
)
from .rehu_document_model import RehuDocumentModel

CUSTOM_CHOICE: Final = "Custom"
"""The first entry of the id cell's list, and the name a license picked there starts with: a license no preset names,
with no URL or text of a preset's. The name is selected for another to be typed over it, or kept as it is."""


class LicensesRowDelegate(RowBandDelegate):
    """Draws a license row as any banded row, with the grip it is dragged by at the left of its id while the rows can
    be dragged, and edits its id with *Custom* and the presets offered, any other id typed beside them
    (:class:`~rehuco_agent.fields.widgets.editable_choice_combo_box.EditableChoiceComboBox`): picking a preset writes
    it at once, picking *Custom* puts that name in the cell, selected, and a preset another row holds cannot be
    picked.

    **While a row is dragged**, the list shows what a card list shows, as the Roots view does: each row paints the
    license :meth:`~borco_pyside.widgets.ReorderDrag.source_at` says is shown there -- selected if that one is -- and
    the shadow's row paints the card list's shadow, across the whole row.

    :param view: the table.
    :param drag: the drag that reorders the rows.
    """

    def __init__(self, view: QAbstractItemView, drag: ReorderDrag) -> None:
        super().__init__(view)
        self.__drag: Final = drag

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        drag = self.__drag
        if drag.active:
            shown = drag.source_at(index.row())
            if shown is None:
                self.__paint_shadow(painter, option, index)
                return
            index = index.model().index(shown, index.column())
            option = LicensesRowDelegate.__as_shown(option, index)
        if index.column() != LICENSE_COLUMN or not index.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        cell = QRect(option.rect)  # pylint: disable=no-member,useless-suppression
        painter.save()
        try:
            color = self.paint_band(painter, opt, index)
            paint_grip(painter, QRect(cell.left(), cell.top(), GRIP_WIDTH, cell.height()), color)
        finally:
            painter.restore()
        rest = QStyleOptionViewItem(option)
        rest.rect = cell.adjusted(GRIP_WIDTH, 0, 0, 0)
        super().paint(painter, rest, index)

    @staticmethod
    def __paint_shadow(painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        """Paint this cell's part of the shadow, which spans the whole row.

        :param painter: the painter.
        :param option: the cell's option.
        :param index: the cell.
        """
        view = cast(QAbstractItemView, option.widget)  # pylint: disable=no-member,useless-suppression
        cell = QRect(option.rect)  # pylint: disable=no-member,useless-suppression
        model = index.model()
        first = view.visualRect(model.index(index.row(), 0))
        last = view.visualRect(model.index(index.row(), model.columnCount() - 1))
        painter.save()
        try:
            painter.setClipRect(cell)
            paint_drag_ghost(
                painter,
                QRectF(first.united(last)),
                option.palette,  # pylint: disable=no-member,useless-suppression
            )
        finally:
            painter.restore()

    @staticmethod
    def __as_shown(option: QStyleOptionViewItem, index: ModelIndex) -> QStyleOptionViewItem:
        """The option a row is painted with when it shows another license than its own: selected if that one is, and
        not hovered, since the pointer is dragging.

        :param option: the row's own option.
        :param index: the cell it shows.
        :returns: the option to paint it with.
        """
        shown = QStyleOptionViewItem(option)
        view = option.widget  # pylint: disable=no-member,useless-suppression
        selection = view.selectionModel() if isinstance(view, QAbstractItemView) else None
        shown.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver)
        if selection is not None and selection.isSelected(index):
            shown.state |= QStyle.StateFlag.State_Selected
        return shown

    @override
    def createEditor(  # noqa: N802  (Qt API)
        self, parent: QWidget, option: QStyleOptionViewItem, index: ModelIndex
    ) -> QWidget:
        if index.column() != LICENSE_COLUMN:
            return super().createEditor(parent, option, index)
        combo = EditableChoiceComboBox((CUSTOM_CHOICE, *ASSET_LICENSES), parent)
        # a preset another row holds cannot be given to this one: it is shown, but cannot be picked
        model = index.model()
        taken = model.taken(index.row()) if isinstance(model, LicensesTableModel) else set()
        items = cast(QStandardItemModel, combo.model())
        for at, license_id in enumerate(ASSET_LICENSES, start=1):
            items.item(at).setEnabled(license_id not in taken)
        # the list of known ids is as wide as its longest, however narrow the cell
        popup = combo.view()
        popup.setMinimumWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width())
        combo.activated.connect(lambda at: self.__take_pick(combo, at))
        return combo

    def __take_pick(self, combo: EditableChoiceComboBox, at: int) -> None:
        """Take what was picked from the id cell's list: *Custom* leaves its name in the cell, selected, for another
        to be typed over it or for it to be kept as it is; a preset is the answer, written at once, and the URL is
        next.

        :param combo: the id cell's editor.
        :param at: the row picked.
        """
        if at == 0:
            combo.setFocus()
            # an editable combo box always has its line
            cast(QLineEdit, combo.lineEdit()).selectAll()
            return
        self.commitData.emit(combo)
        self.closeEditor.emit(combo, QAbstractItemDelegate.EndEditHint.EditNextItem)

    @override
    def setEditorData(self, editor: QWidget, index: ModelIndex) -> None:  # noqa: N802  (Qt API)
        if isinstance(editor, EditableChoiceComboBox):
            editor.set_value(str(index.data(Qt.ItemDataRole.EditRole) or ""))
            return
        super().setEditorData(editor, index)

    @override
    def setModelData(  # noqa: N802  (Qt API)
        self, editor: QWidget, model: QAbstractItemModel, index: ModelIndex
    ) -> None:
        if isinstance(editor, EditableChoiceComboBox):
            model.setData(index, editor.value)
            return
        super().setModelData(editor, model, index)

    @override
    def updateEditorGeometry(  # noqa: N802  (Qt API)
        self, editor: QWidget, option: QStyleOptionViewItem, index: ModelIndex
    ) -> None:
        """Put the editor on the cell, right of the grip in a row that has one.

        :param editor: the editor.
        :param option: the cell's option.
        :param index: the cell.
        """
        rect = QRect(option.rect)  # pylint: disable=no-member,useless-suppression
        if index.column() == LICENSE_COLUMN and index.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            rect.setLeft(rect.left() + GRIP_WIDTH)
        editor.setGeometry(rect)

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API)
        hint = super().sizeHint(option, index)
        if index.column() == LICENSE_COLUMN and index.flags() & Qt.ItemFlag.ItemIsDragEnabled:
            return QSize(hint.width() + GRIP_WIDTH, hint.height())
        return hint


class LicensesGripFilter(GripReorderFilter):
    """Drags a license by its grip, as :class:`~rehuco_agent.grip_reorder.GripReorderFilter` drags a row: a drag
    carries the dragged row, and a drop moves it (:meth:`LicensesTableModel.move`)."""

    @override
    def _carries(self, model: QAbstractItemModel, mime: QMimeData, row: int) -> bool:
        """Whether a drag carries the dragged license.

        :param model: the table's model.
        :param mime: the drag's data.
        :param row: the dragged row.
        :returns: whether the drag names that row.
        """
        return mime.hasFormat(LICENSE_MIME_TYPE) and bytes(mime.data(LICENSE_MIME_TYPE).data()) == str(row).encode()

    @override
    def _move(self, model: QAbstractItemModel, row: int, slot: int) -> None:
        """Move the dragged license to its shadow's place.

        :param model: the table's model.
        :param row: the dragged row.
        :param slot: where it lands.
        """
        if isinstance(model, LicensesTableModel):
            model.move(row, slot)


class LicensesListEditor(ItemListEditor):
    """A record's licenses as a table of id and URL, sized to its rows so it never scrolls, with `ItemListEditor`'s
    add and delete beside it and a grip at each row's left that drags it to another place -- the buttons and the grip
    shown only while the dock edits (:meth:`set_editable`); the four move buttons are never shown, the grip being how a
    row moves. A row is one license, so the selection is one whole row.

    **A row added stays while the dock edits**, however the focus moves -- into the id cell's list, to the text, out
    of the window: `ItemListEditor` drops a blank insert when the user leaves it, and this list never counts a row
    blank (:meth:`row_is_blank`). The rows still without an id go when the editing stops, or the record is saved
    (:meth:`~LicensesTableModel.drop_unnamed`).

    **A preset picked brings its text**, read in the background (:class:`LicenseTextReader`) and held by the document
    if the license is still there when it arrives.

    :param document: the document whose licenses these are.
    :param parent: optional Qt parent.
    """

    def __init__(self, document: RehuDocumentModel, parent: QWidget | None = None) -> None:
        model = LicensesTableModel(document)
        table = ContentSizedTableView()
        drag = ReorderDrag()
        super().__init__(table, model, parent, with_ordering=False, delegate=LicensesRowDelegate(table, drag))
        self.__licenses: Final = model
        """The same model the base holds, at its concrete type."""
        self.__document: Final = document
        self.__reader: Final = LicenseTextReader(self)
        model.preset_chosen.connect(self.__reader.read)
        self.__reader.text_read.connect(self.__on_text_read)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = table.horizontalHeader()
        # the columns share the width equally: an id sized to its text left a row being added a sliver to type into
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        actions = self.item_actions
        # a copy would hold the license's id, which no other row may; a cell opens with a double-click; there are no
        # default licenses to restore
        for action in (actions.duplicate_action, actions.edit_action, actions.reset_action):
            action.setVisible(False)
            table.removeAction(action)
        apply_item_action_icons(self)
        self.__make_reorderable(table, drag)
        self.set_editable(False)
        document.dirty_changed.connect(self.__on_dirty_changed)  # type: ignore[attr-defined]

    def detach(self) -> None:
        """Stop following the document, before this list is destroyed."""
        self.__document.dirty_changed.disconnect(self.__on_dirty_changed)  # type: ignore[attr-defined]
        self.__reader.text_read.disconnect(self.__on_text_read)

    @property
    def licenses(self) -> LicensesTableModel:
        """The rows."""
        return self.__licenses

    def set_editable(self, editable: bool) -> None:
        """Let the licenses be edited, or only read: add, delete and the grips show only while they can be, and a cell
        being typed into is written before they no longer can.

        :param editable: whether they can.
        """
        if not editable:
            self.__commit_open_editor()
            self.__licenses.drop_unnamed()
        self.__licenses.set_editable(editable)
        self.item_actions.setVisible(editable)

    @override
    def row_is_blank(self, row: int) -> bool:
        """Never: a row with nothing in it yet stays until the editing stops (see the class docstring).

        :param row: the row.
        :returns: ``False``.
        """
        return False

    def __on_text_read(self, license_id: str, url: str, terms: LicenseTerms) -> None:
        """Hold the text read for a preset picked, if the record still holds that license with that address -- not
        one picked again, or replaced, while it was read.

        :param license_id: the license.
        :param url: where its text was read.
        :param terms: the text.
        """
        if AssetLicense(license_id, url) in self.__document.licenses:
            self.__document.hold_license_text(license_id, terms)

    def __on_dirty_changed(self, dirty: bool) -> None:
        """Take out the rows still without an id once the record is saved.

        :param dirty: whether the document has unsaved edits.
        """
        if not dirty:
            self.__licenses.drop_unnamed()

    def __commit_open_editor(self) -> None:
        """Write what an open cell holds and close it."""
        view = self.view
        editor = view.indexWidget(view.currentIndex())
        if editor is not None:
            delegate = view.itemDelegate()
            delegate.commitData.emit(editor)
            delegate.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    @staticmethod
    def __make_reorderable(table: QAbstractItemView, drag: ReorderDrag) -> None:
        """Let a license dragged by its grip go to another place, as the Roots view lets a root: the view's own drag
        and its drop line stay off, and the view only takes drops, every one of which the filter answers.

        :param table: the table.
        :param drag: the drag's bookkeeping, shared with the delegate.
        """
        table.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        table.setDefaultDropAction(Qt.DropAction.MoveAction)
        table.setDropIndicatorShown(False)
        table.setDragEnabled(False)
        table.setMouseTracking(True)
        table.viewport().setMouseTracking(True)
        grip = LicensesGripFilter(table, drag)
        table.viewport().installEventFilter(grip)
        # the rows changing under a drag -- the document reverted, say -- abandons it
        model = table.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.rowsMoved):
            signal.connect(grip.abandon)
        model.modelReset.connect(lambda: grip.abandon(None))
