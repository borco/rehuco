"""Whole-app close guard: pick which dirty documents to save before quitting ([[plugins#toolkit-surfaces]])."""

from typing import Final, override

from PySide6.QtCore import QAbstractItemModel, QByteArray, QEvent, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from ..documents.rehu_document_model import RehuDocumentModel
from ..settings.persistent_settings import persistent_settings
from ..settings.unsaved_changes_dialog_settings import UnsavedChangesDialogSettings
from .unsaved_changes_dialog_ui import Ui_UnsavedChangesDialog


class UnsavedChangesDialog(QDialog):
    """Lists dirty documents with a checkbox each (checked by default) and Save Selected/Discard All/Cancel.

    **Save Selected** saves every checked document; the unchecked ones are left dirty (and, since
    this dialog only appears from the whole-app close guard, their edits are discarded along with
    the close). **Discard All** closes without saving anything, regardless of the checkboxes.
    **Cancel** aborts the app close entirely -- see :meth:`MainWindow.closeEvent`.

    Geometry (size/position) is persisted across runs (#38): restored in :meth:`__init__` and
    captured in :meth:`done`, the one hook every exit path (Save Selected, Discard All, Cancel,
    Escape, and the titlebar close button) funnels through.

    :param models: the dirty document models to offer for saving.
    :param parent: optional Qt parent.
    """

    class RowDelegate(QStyledItemDelegate):
        """Toggles a checkable item's check state on any click within its row, not just its checkbox glyph."""

        @override
        def editorEvent(
            self,
            event: QEvent,
            model: QAbstractItemModel,
            option: QStyleOptionViewItem,
            index: QModelIndex | QPersistentModelIndex,
        ) -> bool:
            if event.type() == QEvent.Type.MouseButtonRelease and index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                current = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole))
                toggled = Qt.CheckState.Unchecked if current == Qt.CheckState.Checked else Qt.CheckState.Checked
                model.setData(index, toggled, Qt.ItemDataRole.CheckStateRole)
                return True
            return super().editorEvent(event, model, option, index)

    def __init__(self, models: list[RehuDocumentModel], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__models: Final = models
        self.__discard_all = False

        self.__ui: Final = Ui_UnsavedChangesDialog()
        self.__ui.setupUi(self)
        self.__ui.documents_list_view.setItemDelegate(self.RowDelegate(self))

        button_box = self.__ui.button_box
        button_box.button(QDialogButtonBox.StandardButton.Save).setText("Save Selected")
        discard_all_button = button_box.addButton("Discard All", QDialogButtonBox.ButtonRole.DestructiveRole)
        discard_all_button.clicked.connect(self.__on_discard_all_clicked)

        self.__list_model: Final = QStandardItemModel(self)
        for model in models:
            label = str(model.path) if model.path else "Untitled"
            item = QStandardItem(label)
            item.setEditable(False)
            item.setCheckable(True)
            item.setCheckState(Qt.CheckState.Checked)
            self.__list_model.appendRow(item)
        self.__ui.documents_list_view.setModel(self.__list_model)

        self.__settings: Final = UnsavedChangesDialogSettings()
        self.__settings.load(persistent_settings())
        if self.__settings.geometry:
            self.restoreGeometry(QByteArray(self.__settings.geometry))

    @override
    def done(self, result: int) -> None:
        """Persist the dialog's geometry before closing, on every exit path.

        :param result: the dialog's result code, passed straight through to :meth:`QDialog.done`.
        """
        self.__settings.geometry = bytes(self.saveGeometry().data())
        self.__settings.save(persistent_settings())
        super().done(result)

    def selected_models(self) -> list[RehuDocumentModel]:
        """The models to save: none if Discard All was chosen, otherwise the still-checked ones."""
        if self.__discard_all:
            return []
        return [
            model
            for model, row in zip(self.__models, range(self.__list_model.rowCount()))
            if self.__list_model.item(row).checkState() == Qt.CheckState.Checked
        ]

    def __on_discard_all_clicked(self) -> None:
        self.__discard_all = True
        self.accept()
