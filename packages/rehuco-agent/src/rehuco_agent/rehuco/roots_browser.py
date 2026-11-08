"""The Add Roots dialog's file browser: folders and ``.rehuroot`` files, a ``+`` on the row under the pointer or
current, which stages it -- or every row selected with it -- as roots to add (#578)."""

from pathlib import Path
from typing import Final, override

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QAbstractItemModel, QDir, QEvent, QModelIndex, QPersistentModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QAction, QMouseEvent, QPainter, QPalette
from PySide6.QtWidgets import (
    QFileSystemModel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
    QWidget,
)
from rehuco_core import REHUROOT_SUFFIX

from ..svg_icon_cache import SvgIconCache
from .roots_browser_ui import Ui_RootsBrowser

ADD_ICON: Final = ":/icons/items_add.svg"
"""The ``+`` a row shows, the list editors' own."""

UP_ICON: Final = ":/icons/items_up.svg"
"""The arrow of the button that shows the folder above."""

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a delegate method."""


class AddButtonDelegate(QStyledItemDelegate):
    """Draws a row as the default delegate does, with a ``+`` at its right end while it is under the pointer or
    current; a click on the ``+`` asks for the row to be staged, and does nothing else.

    :param view: the tree it draws, which says which row is current and is told of the click.
    """

    clicked = Signal(object)
    """Emitted with the :class:`~PySide6.QtCore.QModelIndex` whose ``+`` was clicked."""

    def __init__(self, view: QTreeView) -> None:
        super().__init__(view)
        self.__view: Final = view
        self.__icons: Final = SvgIconCache()

    def button_rect(self, rect: QRect) -> QRect:
        """Where a row's ``+`` is.

        :param rect: the row's cell.
        :returns: a square at its right end, as tall as the row.
        """
        side = rect.height()
        return QRect(rect.right() - side + 1, rect.top(), side, side)

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        super().paint(painter, option, index)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)  # type: ignore[operator]
        if not hovered and index != self.__view.currentIndex():
            return
        rect = self.button_rect(option.rect)  # type: ignore[attr-defined]
        color = option.palette.color(QPalette.ColorRole.Text)  # type: ignore[attr-defined]
        icon = self.__icons.icon(ADD_ICON, color)
        icon.paint(painter, rect.adjusted(2, 2, -2, -2))

    @override
    def editorEvent(  # noqa: N802  (Qt API name)
        self, event: QEvent, model: QAbstractItemModel, option: QStyleOptionViewItem, index: ModelIndex
    ) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
            and self.button_rect(option.rect).contains(event.position().toPoint())  # type: ignore[attr-defined]
        ):
            self.clicked.emit(self.__view.model().index(index.row(), index.column(), index.parent()))
            return True
        return super().editorEvent(event, model, option, index)


class RootsBrowser(QWidget):
    """A tree of the folders and ``.rehuroot`` files under a folder, many selectable at once, and a field naming that
    folder with a button to go up a level. The ``+`` of a row stages it -- or, when the row is selected, every
    selected row, in the tree's order -- and leaves the selection as it was. The listing is
    :class:`~PySide6.QtWidgets.QFileSystemModel`'s, which reads on a thread of its own, so a share never holds up the
    dialog.

    :param parent: optional Qt parent.
    """

    add_requested = Signal(object)
    """Emitted with the ``list`` of :class:`~pathlib.Path` to stage, in the tree's order."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_RootsBrowser()
        self.__ui.setupUi(self)
        model = QFileSystemModel(self)
        model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        model.setNameFilters([f"*{REHUROOT_SUFFIX}"])
        model.setNameFilterDisables(False)
        model.setRootPath("")
        self.__model: Final = model
        tree = self.__ui.tree_view
        tree.setModel(model)
        for column in range(1, model.columnCount()):
            tree.hideColumn(column)
        tree.setMouseTracking(True)
        self.__delegate: Final = AddButtonDelegate(tree)
        tree.setItemDelegate(self.__delegate)
        self.__delegate.clicked.connect(self.__on_add_clicked)
        self.__up: Final = QAction("Up", self)
        ActionIconThemeHandler(self.__up, UP_ICON)
        self.__ui.up_button.setDefaultAction(self.__up)
        self.__up.triggered.connect(self.__go_up)
        self.__ui.path_edit.returnPressed.connect(lambda: self.show_folder(Path(self.__ui.path_edit.text().strip())))

    @property
    def tree_view(self) -> QTreeView:
        """The tree, for tests."""
        return self.__ui.tree_view

    @property
    def folder(self) -> Path:
        """The folder the tree shows."""
        return Path(self.__model.filePath(self.__ui.tree_view.rootIndex()))

    def show_folder(self, folder: Path) -> None:
        """Show what is under a folder; a path that is no folder is left in the field, and the tree stays.

        :param folder: the folder.
        """
        index = self.__model.index(str(folder))
        if not index.isValid() or not self.__model.isDir(index):
            return
        self.__ui.tree_view.setRootIndex(index)
        self.__ui.path_edit.setText(str(folder))

    def index_of(self, path: Path) -> QModelIndex:
        """The tree's row for a path, for tests.

        :param path: the path.
        :returns: its row; invalid when it is not one.
        """
        return self.__model.index(str(path))

    def stage(self, index: QModelIndex) -> None:
        """Do what the ``+`` of a row does.

        :param index: the row.
        """
        self.__on_add_clicked(index)

    def __on_add_clicked(self, index: QModelIndex) -> None:
        """Ask for the row to be staged, or every selected row when it is one of them.

        :param index: the row whose ``+`` was clicked.
        """
        tree = self.__ui.tree_view
        selection = tree.selectionModel()
        if selection is not None and selection.isSelected(index):
            rows = sorted(selection.selectedRows(), key=RootsBrowser.tree_order)
        else:
            rows = [index]
        self.add_requested.emit([Path(self.__model.filePath(row)) for row in rows])

    @staticmethod
    def tree_order(index: QModelIndex) -> tuple[int, ...]:
        """Where a row stands in the tree's order, whether or not it is on screen: its row under each ancestor, from
        the top down.

        :param index: the row.
        :returns: the key rows sort by.
        """
        rows: list[int] = []
        while index.isValid():
            rows.append(index.row())
            index = index.parent()
        return tuple(reversed(rows))

    def __go_up(self) -> None:
        """Show the folder above the one shown."""
        folder = self.folder
        if folder.parent != folder:
            self.show_folder(folder.parent)
