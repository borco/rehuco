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

from ..persistent_settings import persistent_settings
from ..settings_dialog_settings import SettingsDialogSettings
from .settings_dialog_ui import Ui_SettingsDialog
from .settings_frame_filter import SettingsFrameFilter
from .settings_page import SettingsPage

PAGE_ROLE: Final = Qt.ItemDataRole.UserRole + 1
"""Item-data role storing each category-tree row's page widget, for selection-driven page switching."""

FILTER_ROLE: Final = Qt.ItemDataRole.UserRole + 2
"""Item-data role storing each row's `SettingsFrameFilter`, for page- and frame-level filtering."""


class SettingsDialog(QWidget):
    """The settings dialog's shell: a filterable category tree on the left, the selected category's
    page on the right, and a toolbar to apply/reset changes (#47).

    Holds no settings pages itself -- :meth:`add_page` registers each one (a plain ``QWidget``
    additionally satisfying `SettingsPage`, mirroring the field toolkit's structural-protocol style),
    building this dialog's tree row and stacked-widget page for it. Pages themselves land in later
    slices (#47); this shell works correctly with zero pages registered.

    The category tree is two levels deep at most (#76): a page registered with a ``group`` becomes a
    leaf under that group's row, and one registered without stays a top-level row of its own. A group
    row carries no page -- it is a header, so selecting it leaves the shown page as it is.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_SettingsDialog()
        self.__ui.setupUi(self)

        self.__model: Final = QStandardItemModel(self)
        self.__groups: Final[dict[str, QStandardItem]] = {}
        self.__proxy: Final = self.CategoryFilterProxyModel(self)
        self.__proxy.setSourceModel(self.__model)
        self.__ui.category_tree.setModel(self.__proxy)
        # selectionModel() is None only before a model is set (QAbstractItemView.setModel just did)
        selection_model = cast(QItemSelectionModel, self.__ui.category_tree.selectionModel())
        selection_model.currentChanged.connect(self.__on_current_changed)

        self.__ui.show_full_page_check_box.set_text("Show full page if title matches")
        self.__ui.show_full_group_check_box.set_text("Show full group if title matches")

        # Restore the filter *before* wiring it up, so seeding the widgets doesn't fire the handlers
        # below; the proxy is seeded by hand for the same reason (no signal to ride in on). Each
        # page's own frame filter needs no seeding here: a page is frame-filtered when it becomes
        # current, and the first one added becomes current immediately (see add_page).
        self.__settings: Final = SettingsDialogSettings()
        self.__settings.load(persistent_settings())
        self.__ui.filter_edit.setText(self.__settings.filter_text)
        self.__ui.show_full_page_check_box.set_checked(self.__settings.show_full_page_on_title_match)
        self.__ui.show_full_group_check_box.set_checked(self.__settings.show_full_group_on_title_match)
        self.__proxy.set_filter_text(self.__settings.filter_text)
        self.__proxy.set_show_full_group(self.__settings.show_full_group_on_title_match)

        self.__ui.filter_edit.textChanged.connect(self.__proxy.set_filter_text)
        self.__ui.filter_edit.textChanged.connect(self.__apply_filter_to_current_page)
        # A filtered-out group row takes its (still-matching) leaves' expansion state with it, so
        # re-expand after every re-filter -- otherwise a page can survive the filter yet stay unseen.
        self.__ui.filter_edit.textChanged.connect(self.__ui.category_tree.expandAll)
        self.__ui.show_full_page_check_box.toggled.connect(self.__apply_filter_to_current_page)
        self.__ui.show_full_group_check_box.toggled.connect(self.__proxy.set_show_full_group)
        self.__ui.show_full_group_check_box.toggled.connect(self.__ui.category_tree.expandAll)

        self.__ui.apply_all_action.triggered.connect(self.__apply_all)
        self.__ui.apply_current_page_action.triggered.connect(self.__apply_current_page)
        self.__ui.reset_all_action.triggered.connect(self.__reset_all)
        self.__ui.reset_current_page_action.triggered.connect(self.__reset_current_page)

    def add_page(self, page: SettingsPage, group: str | None = None) -> None:
        """Register ``page`` as a new category: adds its tree row and stacked page.

        The first page added becomes the initially-selected one.

        :param page: the page to add -- a ``QWidget`` that also satisfies `SettingsPage`.
        :param group: the group to nest this page's row under, creating that group's row on first
            use; ``None`` (the default) makes it a top-level row of its own (#76).
        """
        widget = cast(QWidget, page)
        item = QStandardItem(page.title)
        item.setData(widget, PAGE_ROLE)
        item.setData(SettingsFrameFilter(widget, page.title), FILTER_ROLE)
        item.setEditable(False)
        parent = self.__model if group is None else self.__group_item(group)
        parent.appendRow(item)
        self.__ui.page_stack.addWidget(widget)
        # A group row is judged by its pages, so the one just appended can flip its parent's verdict:
        # the group was rejected on insertion, when it still had no pages to accept it (Qt re-tests
        # only the inserted row itself, never its parent). Matters whenever pages are registered
        # while a filter is already live -- as they are on startup, with a restored filter (#76).
        self.__proxy.invalidate()
        self.__ui.category_tree.expandAll()

        if self.__ui.page_stack.count() == 1:
            index = self.__proxy.mapFromSource(item.index())
            self.__ui.category_tree.setCurrentIndex(index)

    def save_filter_state(self) -> None:
        """Persist the filter text and both "show full ... if title matches" toggles (#76).

        Called from ``MainWindow.closeEvent``, alongside the app's other at-shutdown saves -- this
        dialog lives in a dock, so it has no close/done path of its own to save from the way
        `UnsavedChangesDialog` (a real ``QDialog``) does from ``done()``.
        """
        self.__settings.filter_text = self.__ui.filter_edit.text()
        self.__settings.show_full_page_on_title_match = self.__ui.show_full_page_check_box.is_checked()
        self.__settings.show_full_group_on_title_match = self.__ui.show_full_group_check_box.is_checked()
        self.__settings.save(persistent_settings())

    def __group_item(self, group: str) -> QStandardItem:
        """The row for the group titled ``group``, appended to the tree on first use.

        :param group: the group's title.
        :returns: that group's (page-less) header row.
        """
        if (item := self.__groups.get(group)) is None:
            item = QStandardItem(group)
            item.setEditable(False)
            self.__model.appendRow(item)
            self.__groups[group] = item  # pylint: disable=unsupported-assignment-operation
        return item

    def __pages(self) -> list[SettingsPage]:
        """Every registered page, in tree order (a group's pages together, at the group's position)."""
        pages: list[SettingsPage] = []
        for row in range(self.__model.rowCount()):
            item = self.__model.item(row)
            if item is None:  # pragma: no cover  (a row within rowCount() always has an item)
                continue
            if (page := item.data(PAGE_ROLE)) is not None:
                pages.append(cast(SettingsPage, page))
                continue
            for child_row in range(item.rowCount()):  # a page-less row is a group: recurse one level
                pages.append(cast(SettingsPage, item.child(child_row).data(PAGE_ROLE)))
        return pages

    def __current_item(self) -> QStandardItem | None:
        """The source-model item for the currently-selected tree row, or ``None`` if none is."""
        index = self.__ui.category_tree.currentIndex()
        if not index.isValid():
            return None
        return self.__model.itemFromIndex(self.__proxy.mapToSource(index))

    def __current_page(self) -> SettingsPage | None:
        """The page whose row is currently selected in the tree.

        :returns: that page, or ``None`` if no row is selected or the selected row is a group header
            (which carries no page of its own).
        """
        if (item := self.__current_item()) is None:
            return None
        return cast(SettingsPage | None, item.data(PAGE_ROLE))

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
            self.__apply_filter_to_current_page()

    def __apply_filter_to_current_page(self, *_args: object) -> None:
        """Re-run the frame-level filter on the currently-shown page.

        Called when the filter text or the "show full page if title matches" toggle changes, and
        when a different page becomes current -- so the visible page always reflects the live filter.
        A selected group header has no page and no frames of its own, so there is nothing to filter.

        :param _args: the triggering signal's argument (filter text or toggle state); unused, the
            current values are read straight off the widgets.
        """
        del _args
        if (item := self.__current_item()) is None:
            return
        frame_filter = cast(SettingsFrameFilter | None, item.data(FILTER_ROLE))
        if frame_filter is not None:
            frame_filter.apply(self.__ui.filter_edit.text(), self.__ui.show_full_page_check_box.is_checked())

    def __apply_all(self) -> None:
        """Apply every registered page's changes."""
        for page in self.__pages():
            page.save_changes()

    def __apply_current_page(self) -> None:
        """Apply only the currently-selected page's changes."""
        if (page := self.__current_page()) is not None:
            page.save_changes()

    def __reset_all(self) -> None:
        """Discard every registered page's in-progress changes."""
        for page in self.__pages():
            page.drop_changes()

    def __reset_current_page(self) -> None:
        """Discard only the currently-selected page's in-progress changes."""
        if (page := self.__current_page()) is not None:
            page.drop_changes()

    class CategoryFilterProxyModel(QSortFilterProxyModel):
        """Shows only rows whose page title or frame text contains the filter text, case-insensitive.

        A plain-substring match against the row's `SettingsFrameFilter` (not a regex, unlike Qt's
        own ``setFilterFixedString``/``filterRegularExpression`` -- their round trip would need
        un-escaping the fixed-string-escaped pattern back to plain text to match against, which
        :meth:`set_filter_text` avoids by keeping its own plain-text copy).

        Group rows carry no page: one is shown exactly when at least one of its pages is (#76). Qt
        hides a rejected parent's whole subtree, so a group must accept on its children's behalf --
        it can never be shown "empty", and a page can never be hidden by its group alone.
        """

        def __init__(self, parent: QObject | None = None) -> None:
            super().__init__(parent)
            self.__filter_text = ""
            self.__show_full_group = False

        def set_filter_text(self, text: str) -> None:
            """Update the filter text and re-evaluate every row.

            :param text: the text to match page titles/field labels against, case-insensitively.
            """
            self.__filter_text = text
            # invalidateFilter()/invalidateRowsFilter() are both deprecated in this Qt version;
            # invalidate() is the plain, non-deprecated equivalent (re-sorts too, harmless here --
            # this proxy never overrides lessThan, so rows keep the source model's own order).
            self.invalidate()

        def set_show_full_group(self, show_full_group: bool) -> None:
            """Set whether a group's title matching shows every page under it, and re-evaluate (#76).

            :param show_full_group: when ``True``, a page whose group's title matches is shown even
                if the page's own title/fields don't; when ``False``, filtering is page-scoped and a
                group's title has no say in its pages' visibility.
            """
            self.__show_full_group = show_full_group
            self.invalidate()

        @override
        def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
            """Accept every row when the filter is empty; otherwise accept a page row per
            :meth:`__accepts_page` and a group row when any of its pages is accepted.

            :param source_row: the row to test, within ``source_parent``.
            :param source_parent: the source model's parent index -- the invisible root for a group
                or ungrouped page row, a group's index for a grouped page's row (#76).
            :returns: whether ``source_row`` should be shown.
            """
            if not self.__filter_text:
                return True
            model = cast(QStandardItemModel, self.sourceModel())
            item = model.itemFromIndex(model.index(source_row, 0, source_parent))
            if item.data(PAGE_ROLE) is not None:
                return self.__accepts_page(item)
            return any(self.__accepts_page(item.child(row)) for row in range(item.rowCount()))

        def __accepts_page(self, item: QStandardItem) -> bool:
            """Whether ``item``'s page is shown: its own title or a frame's text matches the filter,
            or -- with "show full group if title matches" on -- its group's title does.

            :param item: the page's source-model row.
            :returns: whether the page should be shown.
            """
            page = cast(SettingsPage, item.data(PAGE_ROLE))
            frame_filter = cast(SettingsFrameFilter, item.data(FILTER_ROLE))
            needle = self.__filter_text.lower()
            haystacks = [page.title, *frame_filter.field_labels()]
            if any(needle in haystack.lower() for haystack in haystacks):
                return True
            group = item.parent()
            return self.__show_full_group and group is not None and needle in group.text().lower()
