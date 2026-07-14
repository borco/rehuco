"""The lightbox-curation editor: a checkable screenshot list beside a sized preview ([[plugins#field-toolkit]], #27).

A two-pane :class:`QSplitter` (the split position rides along in the saved dock layout): on the left a
:class:`QTreeView` of *all* ``<stem>NN`` screenshot siblings, each checked by default and showing its
pixel dimensions and file size; unchecking one **hides** it from the lightbox. On the right, a preview
of the selected item with its pixel dimensions in a bottom-right overlay. The UI is the inverse of
storage -- checked = visible, and only the hidden exceptions are emitted -- because checked-by-default
reads more naturally ([[data-model#image-meanings]]).
"""

from pathlib import Path
from typing import Final, override

import humanize
from borco_pyside.core import SimpleProperty
from PIL import Image
from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent, QShowEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QGridLayout, QHeaderView, QLabel, QSizePolicy, QSplitter, QTreeView, QWidget

from rehuco_agent.documents.image_scanner import ImageScanner

PATH_ROLE: Final = Qt.ItemDataRole.UserRole
"""The item-data role storing each list entry's screenshot :class:`~pathlib.Path`."""

NAME_COLUMN: Final = 0
DIMENSIONS_COLUMN: Final = 1
SIZE_COLUMN: Final = 2


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

    Left pane -- every screenshot as a checkable row (checked = shown in the lightbox), with its pixel
    dimensions and file size read from disk into two further columns; toggling a row re-emits
    :attr:`hidden_changed` with the current hidden filenames. Right pane -- the selected screenshot
    scaled to fit, with a ``W x H`` pixel-dimension overlay pinned bottom-right.

    Holds its own :attr:`image_scanner`, so it can re-fetch its screenshots and rebuild itself whenever
    that changes (e.g. a `.tc` -> `.rehu` conversion switching naming conventions,
    [[acquisition-tooling#tc-to-rehu]]) without its owner having to push a fresh file list explicitly.

    :param parent: optional Qt parent.
    """

    hidden_changed = Signal(list)
    """Fires with the current list of hidden screenshot filenames whenever a row is checked/unchecked."""

    image_scanner = SimpleProperty[ImageScanner | None](None)
    """The strategy resolving this resource's screenshots; ``None`` shows nothing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)

        self.__list_model: Final = QStandardItemModel(self)
        self.__list: Final = QTreeView()
        self.__list.setModel(self.__list_model)
        self.__list.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.__list.setRootIsDecorated(False)
        self.__list.setUniformRowHeights(True)
        self.__list.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.__list.header().setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        self.__list.header().setSectionResizeMode(DIMENSIONS_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        self.__list.header().setSectionResizeMode(SIZE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
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
        self.image_scanner_changed.connect(lambda _scanner: self.__refresh())  # type: ignore[attr-defined]

    def set_hidden(self, hidden: list[str]) -> None:
        """Resync the checked/unchecked rows from ``hidden``, rebuilding from the current scanner.

        Skips a redundant rebuild when ``hidden`` already matches what's shown -- the echo of this
        selector's *own* toggle coming back through the model binding.

        :param hidden: the filenames to leave unchecked.
        """
        if hidden == self.hidden_filenames():
            return
        self.__rebuild(hidden)

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
        self.__list_model.setHorizontalHeaderLabels(["Name", "Dimensions", "Size"])
        for path in paths:
            name_item = QStandardItem(path.name)
            name_item.setData(path, PATH_ROLE)
            name_item.setCheckable(True)
            name_item.setCheckState(Qt.CheckState.Unchecked if path.name in hidden_names else Qt.CheckState.Checked)
            dimensions_text, size_text = self.__metrics(path)
            dimensions_item = QStandardItem(dimensions_text)
            dimensions_item.setEditable(False)
            size_item = QStandardItem(size_text)
            size_item.setEditable(False)
            self.__list_model.appendRow([name_item, dimensions_item, size_item])
        self.__list_model.blockSignals(False)

        if self.__list_model.rowCount():
            self.__list.setCurrentIndex(self.__list_model.index(0, 0))
        else:
            self.__show_preview(QPixmap())

    @staticmethod
    def __metrics(path: Path) -> tuple[str, str]:
        """The ``W x H`` pixel dimensions and humanized file size for ``path``, read from disk.

        Dimensions come from :class:`PIL.Image.Image.size`, a lazy header-only read for these formats
        -- the same convention already used for :meth:`TcScanner`'s slot-winner scoring
        (``rehuco_core.tc_screenshots.__pixel_area``) -- far cheaper than the full-decode
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

    def hidden_filenames(self) -> list[str]:
        """The filenames of every currently-unchecked (hidden-from-lightbox) row, in list order.

        :returns: the hidden screenshot filenames.
        """
        return [
            self.__list_model.item(row, NAME_COLUMN).text()
            for row in range(self.__list_model.rowCount())
            if self.__list_model.item(row, NAME_COLUMN).checkState() == Qt.CheckState.Unchecked
        ]

    def __on_item_changed(self, _item: QStandardItem) -> None:
        """Re-emit :attr:`hidden_changed` with the filenames of every currently-unchecked row.

        :param _item: the item whose check state changed (unused -- the full list is recomputed).
        """
        self.hidden_changed.emit(self.hidden_filenames())

    def __on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Load and preview the newly-selected screenshot.

        :param current: the newly-selected list index, in any column -- the path lives only on the
            row's name-column item, since selecting the row can land on any column.
        :param _previous: the previously-selected index (unused).
        """
        item = self.__list_model.item(current.row(), NAME_COLUMN) if current.isValid() else None
        path = item.data(PATH_ROLE) if item is not None else None
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
