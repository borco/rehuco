"""The lightbox-curation editor: a checkable screenshot list beside a sized preview ([[plugins#field-toolkit]], #27).

A two-pane :class:`QSplitter` (the split position rides along in the saved dock layout): on the left a
:class:`QListView` of *all* ``<stem>NN`` screenshot siblings, each checked by default; unchecking one
**hides** it from the lightbox. On the right, a preview of the selected item with its pixel dimensions
in a bottom-right overlay. The UI is the inverse of storage -- checked = visible, and only the hidden
exceptions are emitted -- because checked-by-default reads more naturally ([[data-model#image-meanings]]).
"""

from pathlib import Path
from typing import Final, override

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent, QShowEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QGridLayout, QLabel, QListView, QSizePolicy, QSplitter, QWidget

PATH_ROLE: Final = Qt.ItemDataRole.UserRole
"""The item-data role storing each list entry's screenshot :class:`~pathlib.Path`."""


class PreviewLabel(QLabel):
    """A label that keeps a source pixmap scaled to fit itself, aspect-ratio preserved.

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


class ImageSelector(QSplitter):
    """A checkable screenshot list beside a sized preview ([[plugins#field-toolkit]], #27).

    Left pane -- every screenshot as a checkable row (checked = shown in the lightbox); toggling a row
    re-emits :attr:`hidden_changed` with the current hidden filenames. Right pane -- the selected
    screenshot scaled to fit, with a ``W x H`` pixel-dimension overlay pinned bottom-right.

    :param parent: optional Qt parent.
    """

    hidden_changed = Signal(list)
    """Fires with the current list of hidden screenshot filenames whenever a row is checked/unchecked."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)

        self.__list_model: Final = QStandardItemModel(self)
        self.__list: Final = QListView()
        self.__list.setModel(self.__list_model)
        self.__list.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.addWidget(self.__list)

        preview_pane = QWidget()
        overlay = QGridLayout(preview_pane)
        overlay.setContentsMargins(0, 0, 0, 0)
        self.__preview: Final = PreviewLabel()
        self.__size_overlay: Final = QLabel()
        self.__size_overlay.setStyleSheet("background: rgba(0, 0, 0, 0.5); color: white; padding: 2px 6px;")
        self.__size_overlay.hide()
        overlay.addWidget(self.__preview, 0, 0)
        overlay.addWidget(self.__size_overlay, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.addWidget(preview_pane)

        self.__list_model.itemChanged.connect(self.__on_item_changed)
        self.__list.selectionModel().currentChanged.connect(self.__on_current_changed)

    def set_images(self, paths: list[Path], hidden: list[str]) -> None:
        """Populate the list with ``paths``, checking each one not named in ``hidden``.

        Rebuilds the whole list. Signals are blocked during the rebuild so seeding never looks like a
        user toggle (no spurious :attr:`hidden_changed`). Selects the first row so the preview is not
        blank when there are images.

        :param paths: every screenshot sibling, in display order.
        :param hidden: the filenames to leave *unchecked* (curated out of the lightbox).
        """
        hidden_names = set(hidden)
        self.__list_model.blockSignals(True)
        self.__list_model.clear()
        for path in paths:
            item = QStandardItem(path.name)
            item.setData(path, PATH_ROLE)
            item.setCheckable(True)
            item.setCheckState(Qt.CheckState.Unchecked if path.name in hidden_names else Qt.CheckState.Checked)
            self.__list_model.appendRow(item)
        self.__list_model.blockSignals(False)

        if self.__list_model.rowCount():
            self.__list.setCurrentIndex(self.__list_model.index(0, 0))
        else:
            self.__show_preview(QPixmap())

    def hidden_filenames(self) -> list[str]:
        """The filenames of every currently-unchecked (hidden-from-lightbox) row, in list order.

        :returns: the hidden screenshot filenames.
        """
        return [
            self.__list_model.item(row).text()
            for row in range(self.__list_model.rowCount())
            if self.__list_model.item(row).checkState() == Qt.CheckState.Unchecked
        ]

    def __on_item_changed(self, _item: QStandardItem) -> None:
        """Re-emit :attr:`hidden_changed` with the filenames of every currently-unchecked row.

        :param _item: the item whose check state changed (unused -- the full list is recomputed).
        """
        self.hidden_changed.emit(self.hidden_filenames())

    def __on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Load and preview the newly-selected screenshot.

        :param current: the newly-selected list index.
        :param _previous: the previously-selected index (unused).
        """
        path = current.data(PATH_ROLE)
        self.__show_preview(QPixmap(str(path)) if isinstance(path, Path) else QPixmap())

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
