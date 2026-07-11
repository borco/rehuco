"""VLC-preferences-style settings shell: filterable category tree + per-category page (#47)."""

from typing import Final, cast, override

from PySide6.QtCore import (
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QWidget

from rehuco_agent.dialogs.settings_dialog_ui import Ui_SettingsDialog
from rehuco_agent.dialogs.settings_page import SettingsPage

PAGE_ROLE: Final = Qt.ItemDataRole.UserRole + 1
"""Item-data role storing each category-tree row's page widget, for selection-driven page switching."""


class SettingsDialog(QWidget):
    """The settings dialog's shell: a filterable category tree on the left, the selected category's
    page on the right, and a toolbar to save/drop changes (#47).

    Holds no settings pages itself -- :meth:`add_page` registers each one (a plain ``QWidget``
    additionally satisfying `SettingsPage`, mirroring the field toolkit's structural-protocol style),
    building this dialog's tree row and stacked-widget page for it. Pages themselves land in later
    slices (#47); this shell works correctly with zero pages registered.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_SettingsDialog()
        self.__ui.setupUi(self)

        self.__model: Final = QStandardItemModel(self)
        self.__proxy: Final = self.CategoryFilterProxyModel(self)
        self.__proxy.setSourceModel(self.__model)
        self.__ui.category_tree.setModel(self.__proxy)
        # selectionModel() is None only before a model is set (QAbstractItemView.setModel just did)
        selection_model = cast(QItemSelectionModel, self.__ui.category_tree.selectionModel())
        selection_model.currentChanged.connect(self.__on_current_changed)

        self.__ui.filter_edit.textChanged.connect(self.__proxy.set_filter_text)

        self.__ui.save_all_action.triggered.connect(self.__save_all)
        self.__ui.save_current_page_action.triggered.connect(self.__save_current_page)
        self.__ui.drop_all_action.triggered.connect(self.__drop_all)
        self.__ui.drop_current_page_action.triggered.connect(self.__drop_current_page)

    def add_page(self, page: SettingsPage) -> None:
        """Register ``page`` as a new category: adds its tree row and stacked page.

        The first page added becomes the initially-selected one.

        :param page: the page to add -- a ``QWidget`` that also satisfies `SettingsPage`.
        """
        widget = cast(QWidget, page)
        item = QStandardItem(page.title)
        item.setData(widget, PAGE_ROLE)
        item.setEditable(False)
        self.__model.appendRow(item)
        self.__ui.page_stack.addWidget(widget)

        if self.__ui.page_stack.count() == 1:
            index = self.__proxy.mapFromSource(item.index())
            self.__ui.category_tree.setCurrentIndex(index)

    def __pages(self) -> list[SettingsPage]:
        """Every registered page, in registration order."""
        pages: list[SettingsPage] = []
        for row in range(self.__model.rowCount()):
            item = self.__model.item(row)
            if item is not None:  # pragma: no branch  (a row within rowCount() always has an item)
                pages.append(cast(SettingsPage, item.data(PAGE_ROLE)))
        return pages

    def __current_page(self) -> SettingsPage | None:
        """The page whose row is currently selected in the tree, or ``None`` if none is."""
        index = self.__ui.category_tree.currentIndex()
        if not index.isValid():
            return None
        source_index = self.__proxy.mapToSource(index)
        item = self.__model.itemFromIndex(source_index)
        return cast(SettingsPage, item.data(PAGE_ROLE)) if item is not None else None

    def __on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        """Show the newly-selected row's page in the stack.

        :param current: the newly-current tree index; unused directly (:meth:`__current_page` reads
            it back off the tree, keeping selection state in one place).
        :param previous: the previously-current tree index; unused.
        """
        del current, previous
        page = self.__current_page()
        if page is not None:
            self.__ui.page_stack.setCurrentWidget(cast(QWidget, page))

    def __save_all(self) -> None:
        """Save every registered page's changes."""
        for page in self.__pages():
            page.save_changes()

    def __save_current_page(self) -> None:
        """Save only the currently-selected page's changes."""
        if (page := self.__current_page()) is not None:
            page.save_changes()

    def __drop_all(self) -> None:
        """Discard every registered page's in-progress changes."""
        for page in self.__pages():
            page.drop_changes()

    def __drop_current_page(self) -> None:
        """Discard only the currently-selected page's in-progress changes."""
        if (page := self.__current_page()) is not None:
            page.drop_changes()

    class CategoryFilterProxyModel(QSortFilterProxyModel):
        """Shows only rows whose page title or field labels contain the filter text, case-insensitive.

        A plain-substring match against :meth:`SettingsPage.field_labels` (not a regex, unlike Qt's
        own ``setFilterFixedString``/``filterRegularExpression`` -- their round trip would need
        un-escaping the fixed-string-escaped pattern back to plain text to match against, which
        :meth:`set_filter_text` avoids by keeping its own plain-text copy).
        """

        def __init__(self, parent: QObject | None = None) -> None:
            super().__init__(parent)
            self.__filter_text = ""

        def set_filter_text(self, text: str) -> None:
            """Update the filter text and re-evaluate every row.

            :param text: the text to match page titles/field labels against, case-insensitively.
            """
            self.__filter_text = text
            # invalidateFilter()/invalidateRowsFilter() are both deprecated in this Qt version;
            # invalidate() is the plain, non-deprecated equivalent (re-sorts too, harmless here --
            # this proxy never overrides lessThan, so rows keep the source model's own order).
            self.invalidate()

        @override
        def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
            """Accept every row when the filter is empty, or when the row's page title or any of its
            field labels contains the filter text (case-insensitive).

            :param source_row: the row, within the flat (single-level) source model, to test.
            :param source_parent: the source model's parent index; always the invisible root, since
                the category tree has no nested sub-categories.
            :returns: whether ``source_row`` should be shown.
            """
            del source_parent
            if not self.__filter_text:
                return True
            model = cast(QStandardItemModel, self.sourceModel())
            item = model.item(source_row)
            if item is None:  # pragma: no cover  (Qt only calls this for a row the model actually has)
                return True
            page = cast(SettingsPage, item.data(PAGE_ROLE))
            needle = self.__filter_text.lower()
            haystacks = [page.title, *page.field_labels()]
            return any(needle in haystack.lower() for haystack in haystacks)
