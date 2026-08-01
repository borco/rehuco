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
from PySide6.QtWidgets import QBoxLayout, QFrame, QScrollArea, QWidget

from ..persistent_settings import persistent_settings
from ..settings_dialog_settings import SettingsDialogSettings
from .settings_block_column import SettingsBlockColumn
from .settings_dialog_ui import Ui_SettingsDialog
from .settings_frame_filter import SettingsFrameFilter
from .settings_page import SettingsPage

PAGE_ROLE: Final = Qt.ItemDataRole.UserRole + 1
"""Item-data role storing each category-tree row's page widget, for selection-driven page switching."""

FILTER_ROLE: Final = Qt.ItemDataRole.UserRole + 2
"""Item-data role storing each row's `SettingsFrameFilter`, for page- and frame-level filtering."""


class SettingsDialog(QWidget):  # pylint: disable=too-many-instance-attributes
    """The settings dialog's shell: a filterable category tree on the left, the selected category's
    page on the right, and a toolbar to apply/reset changes (#47).

    Holds no settings pages itself -- :meth:`add_page` registers each one (a plain ``QWidget``
    additionally satisfying `SettingsPage`, mirroring the field toolkit's structural-protocol style),
    building this dialog's tree row and stacked-widget page for it. Pages themselves land in later
    slices (#47); this shell works correctly with zero pages registered.

    The category tree is two levels deep at most (#76): a page registered with a ``group`` becomes a
    leaf under that group's row, and one registered without stays a top-level row of its own. A group
    row carries no page -- it is a header; selecting it shows every page under it, stacked in one
    scrolling column instead (#230).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_SettingsDialog()
        self.__ui.setupUi(self)

        self.__model: Final = QStandardItemModel(self)
        self.__groups: Final[dict[str, QStandardItem]] = {}
        self.__scroll_areas: Final[dict[QWidget, QScrollArea]] = {}
        self.__group_columns: Final[dict[str, SettingsBlockColumn]] = {}
        self.__group_scroll_areas: Final[dict[str, QScrollArea]] = {}
        # Where each page's blocks came from, so they can be put back exactly as the page declared
        # them: the index each sits at in the page's own layout, and whether it is the one stretched
        # to fill what the others leave (see __restore_blocks).
        self.__page_blocks: Final[dict[QWidget, list[tuple[QFrame, int, bool]]]] = {}
        self.__blank_page: Final = QWidget(self)
        self.__ui.page_stack.addWidget(self.__blank_page)
        # Which *source* row the stack is on. The tree's own currentIndex cannot answer this: it is a
        # proxy index, and filtering a row out destroys it (Qt does not put it back when the row
        # returns). The source model is never filtered, so a row taken from it stays valid throughout.
        self.__shown_row: QStandardItem | None = None
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
        # last of each chain: both re-filter the tree above, and this reads the row count they leave
        self.__ui.filter_edit.textChanged.connect(self.__sync_no_match_state)
        self.__ui.show_full_group_check_box.toggled.connect(self.__sync_no_match_state)

        self.__ui.apply_all_action.triggered.connect(self.__apply_all)
        self.__ui.apply_current_page_action.triggered.connect(self.__apply_current_page)
        self.__ui.reset_all_action.triggered.connect(self.__reset_all)
        self.__ui.reset_current_page_action.triggered.connect(self.__reset_current_page)

    def add_page(self, page: SettingsPage, group: str | None = None) -> None:
        """Register ``page`` as a new category: adds its tree row and stacked page.

        The first page added becomes the initially-selected one. The page is shown through a scroll
        area of its own (:meth:`__scroll_area_for`), so it is the stack -- and nothing around it -- that
        runs out of room when the dialog is small.

        :param page: the page to add -- a ``QWidget`` that also satisfies `SettingsPage`.
        :param group: the group to nest this page's row under, creating that group's row on first
            use; ``None`` (the default) makes it a top-level row of its own (#76).
        """
        widget = cast(QWidget, page)
        item = QStandardItem(page.title)
        item.setData(widget, PAGE_ROLE)
        frame_filter = SettingsFrameFilter(widget, page.title)
        item.setData(frame_filter, FILTER_ROLE)
        item.setEditable(False)
        self.__record_blocks(page, frame_filter)
        parent = self.__model if group is None else self.__group_item(group)
        parent.appendRow(item)
        self.__ui.page_stack.addWidget(self.__scroll_area_for(widget))
        # A group row is judged by its pages, so the one just appended can flip its parent's verdict:
        # the group was rejected on insertion, when it still had no pages to accept it (Qt re-tests
        # only the inserted row itself, never its parent). Matters whenever pages are registered
        # while a filter is already live -- as they are on startup, with a restored filter (#76).
        self.__proxy.invalidate()
        self.__ui.category_tree.expandAll()

        # Checked against __scroll_areas, not page_stack.count(): a group's own scroll area (#230) also
        # occupies a stack slot, so the stack could already hold 2 widgets (group + this first page).
        if len(self.__scroll_areas) == 1:
            index = self.__proxy.mapFromSource(item.index())
            self.__ui.category_tree.setCurrentIndex(index)

    def restore_selected_page(self) -> None:
        """Show the page or group saved by the last :meth:`save_filter_state` call, if it is still
        registered (#228, #230).

        Called once by `MainWindow`, after every settings page has been registered -- `add_page`'s own
        "first page added becomes current" side effect has already picked a page by then, so this is
        what corrects that guess. A title matching nothing registered on this platform (e.g. one saved
        under a different OS's page), or no title at all (nothing was ever saved), leaves that first
        page selected instead.

        The stack and the tree are separate (#76): a page currently filtered out of the tree by the
        restored filter text is still the one shown here, just with no tree row to reflect it as current.
        A restored filter matching *nothing* is the exception -- there is no tree left to be separate
        from, so the blank page wins and this one is what comes back when the filter is loosened (#230).
        """
        if not self.__settings.selected_page_title:
            return
        if (item := self.__item_for_title(self.__settings.selected_page_title)) is None:
            return
        self.__show_row(item)
        self.__sync_no_match_state()

    def __show_row(self, item: QStandardItem) -> None:
        """Show ``item``'s page (or, for a group row, its stacked column) and select it in the tree.

        **The one way the stack is ever driven**, so recording the row here is what makes
        :attr:`__shown_row` true by construction rather than by everyone remembering to update it.

        The tree selection is only set when the row is actually visible: a row the live filter hides
        has no index to be current, which is the stack-and-tree separation #228 relies on.

        :param item: the page or group row to show.
        """
        self.__shown_row = item
        if (page := item.data(PAGE_ROLE)) is not None:
            self.__show_standalone_page(cast(QWidget, page))
        else:
            self.__show_group(item)
        self.__apply_filter_to_row(item)
        proxy_index = self.__proxy.mapFromSource(item.index())
        if proxy_index.isValid():
            self.__ui.category_tree.setCurrentIndex(proxy_index)

    def __sync_no_match_state(self, *_args: object) -> None:
        """Show a blank page while the filter matches nothing, and put back what was showing once it
        matches something again (#230).

        A filter narrowed past its last match used to leave the previously-shown page standing beside
        an empty tree, which reads as a page that survived a filter nothing survived. Going blank says
        plainly that nothing matched.

        Coming back has to be done by hand: Qt drops the tree's current row when the filter hides it
        and **does not restore it** when the row reappears, so one stray keystroke would otherwise
        leave the right-hand side empty until something was clicked. Nothing extra is remembered for
        that -- blanking leaves :attr:`__shown_row` alone, and a *source* row survives any amount of
        filtering, so the row to go back to is simply the one the stack was already on.

        It goes back **only if the new filter still shows that row** -- a typo typed and deleted lands
        back where it left off. Any other filter is a different question being asked, not a return to
        the old one: pasting over ``imagesx`` with ``identity`` must not bring Images back, least of all
        while the tree lists only Identity. In that case the first visible row is shown instead, so a
        tree with rows in it is never left standing beside a blank page.

        :param _args: the triggering signal's argument (filter text or toggle state); unused, the tree
            is asked directly.
        """
        del _args
        showing_blank = self.__ui.page_stack.currentWidget() is self.__blank_page
        if self.__proxy.rowCount() == 0:
            self.__ui.page_stack.setCurrentWidget(self.__blank_page)
            return
        if not showing_blank:
            return
        if self.__shown_row is not None and self.__proxy.mapFromSource(self.__shown_row.index()).isValid():
            self.__show_row(self.__shown_row)
            return
        self.__show_first_visible_row()

    def __show_first_visible_row(self) -> None:
        """Show whichever row the filtered tree lists first, selecting it (#230).

        The fallback for leaving a no-match filter with nowhere particular to return to. A group row
        counts: shown, it stacks whichever of its pages the filter kept, which is as good an answer to
        the new filter as any single page under it.
        """
        index = self.__proxy.index(0, 0)
        if not index.isValid():  # pragma: no cover  (only reached with rows present)
            return
        item = self.__model.itemFromIndex(self.__proxy.mapToSource(index))
        if item is not None:  # pragma: no branch  (a visible proxy row always maps to a source item)
            self.__show_row(item)

    def save_filter_state(self) -> None:
        """Persist the filter text, both "show full ... if title matches" toggles, and the title of
        the page or group currently shown (#76, #228, #230).

        Called from ``MainWindow.closeEvent``, alongside the app's other at-shutdown saves -- this
        dialog lives in a dock, so it has no close/done path of its own to save from the way
        `UnsavedChangesDialog` (a real ``QDialog``) does from ``done()``. The title is read off the
        stack (:meth:`__shown_title`), not the tree's selected row: the two diverge when the shown
        page's row is hidden by the live filter -- and what the next launch restores is what was
        *shown* (#228).
        """
        self.__settings.filter_text = self.__ui.filter_edit.text()
        self.__settings.show_full_page_on_title_match = self.__ui.show_full_page_check_box.is_checked()
        self.__settings.show_full_group_on_title_match = self.__ui.show_full_group_check_box.is_checked()
        if (title := self.__shown_title()) is not None:
            self.__settings.selected_page_title = title
        self.__settings.save(persistent_settings())

    def __scroll_area_for(self, widget: QWidget) -> QScrollArea:
        """Wrap ``widget`` in the scroll area it is shown through, and remember which is whose (#229).

        **One scroll area per page, not one around the stack.** A ``QStackedWidget`` reports its
        *tallest* page's height as its own, so a single scroll area around the stack would scroll every
        page by the longest one -- a two-row page would get a scrollbar and a page's worth of blank
        space below it. Wrapping each page instead lets a short one sit still while a long one scrolls.

        ``setWidgetResizable`` is what hands the page the viewport's width, which is what a wrapping
        paragraph needs before it can say how tall it is; the frame is dropped because the splitter
        already separates this side from the tree.

        :param widget: the page to wrap.
        :returns: that page's scroll area, to be added to the stack.
        """
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(widget)
        self.__scroll_areas[widget] = area  # pylint: disable=unsupported-assignment-operation
        return area

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
            self.__build_group_view(group)
        return item

    def __build_group_view(self, group: str) -> None:
        """Build ``group``'s block column and its scroll area, added to the page stack (#230).

        Created once, on the group's first page -- the blocks themselves join it later, when the
        group's row becomes current (:meth:`__show_group`), the same lazy split
        ``__group_item``/``add_page`` already uses between a group's tree row and its pages.

        :param group: the group's title.
        """
        column = SettingsBlockColumn(self)
        self.__group_columns[group] = column  # pylint: disable=unsupported-assignment-operation
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(column)
        self.__group_scroll_areas[group] = area  # pylint: disable=unsupported-assignment-operation
        self.__ui.page_stack.addWidget(area)

    def __record_blocks(self, page: SettingsPage, frame_filter: SettingsFrameFilter) -> None:
        """Note where ``page``'s blocks sit in its own layout, so they can be put back there (#230).

        Read once, at registration, while the page is still exactly as its ``.ui`` built it. A block's
        index is its position among the page's own layout items, and it *fills* when the page stretched
        it -- the one block, if any, that takes the height the others leave (`DescriptionsPage`'s CSS
        editor is the only one today). Both have to be captured before a group column ever borrows the
        blocks, because taking a widget out of a box layout drops the stretch factor with it.

        :param page: the page being registered.
        :param frame_filter: that page's filter, which already discovered its blocks.
        """
        widget = cast(QWidget, page)
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):  # pragma: no cover  (every page's root is a box layout)
            return
        items = [layout.itemAt(index) for index in range(layout.count())]
        indexes = {item.widget(): index for index, item in enumerate(items) if item is not None}
        self.__page_blocks[widget] = [  # pylint: disable=unsupported-assignment-operation
            (block, index, layout.stretch(index) > 0)
            for block in frame_filter.blocks()
            if (index := indexes.get(block)) is not None
        ]

    def __show_group(self, group_item: QStandardItem) -> None:
        """Show the blocks of every page under ``group_item``, in tree order, in one column (#230).

        The column takes each page's *blocks*, not the page widget: a page's own layout is written for
        being shown alone, and stacking three of them let each one's trailing spacer claim a share of
        the height (see `SettingsBlockColumn`).

        Rebuilt on every showing, since a page shown on its own in between will have taken its blocks
        back.

        :param group_item: the group's (page-less) tree row.
        """
        group = group_item.text()
        sections: list[tuple[str, list[QFrame]]] = []
        for row in range(group_item.rowCount()):
            page = cast(SettingsPage, group_item.child(row).data(PAGE_ROLE))
            blocks = [block for block, _, _ in self.__page_blocks.get(cast(QWidget, page), [])]
            sections.append((page.title, blocks))
        self.__group_columns[group].set_sections(sections)
        self.__ui.page_stack.setCurrentWidget(self.__group_scroll_areas[group])

    def __restore_blocks(self, widget: QWidget) -> None:
        """Put ``widget``'s blocks back into its own layout, exactly where the page declared them (#230).

        A no-op unless a group column currently holds them. Re-inserted in ascending index so each
        lands at its own position, and the page's stretch is re-applied: a box layout keeps stretch by
        item, so a block taken out and put back comes home with that forgotten -- which for
        `DescriptionsPage` is the difference between a CSS editor that fills the page and one squeezed
        to a couple of rows.

        :param widget: the page widget to restore.
        """
        layout = widget.layout()
        if not isinstance(layout, QBoxLayout):  # pragma: no cover  (every page's root is a box layout)
            return
        for block, index, fills in self.__page_blocks.get(widget, []):
            if (owner := block.parentWidget()) is widget:
                continue
            # a borrowed block is always in a group column's layout -- nothing else ever holds one
            if owner is not None and (owner_layout := owner.layout()) is not None:  # pragma: no branch
                owner_layout.removeWidget(block)
            layout.insertWidget(index, block)
            if fills:
                layout.setStretch(index, 1)

    def __show_standalone_page(self, widget: QWidget) -> None:
        """Show ``widget``'s own scroll area in the stack, pulling it out of a group view first if needed.

        :param widget: the page widget to show on its own.
        """
        self.__restore_blocks(widget)
        self.__ui.page_stack.setCurrentWidget(self.__scroll_areas[widget])

    def __item_for_title(self, title: str) -> QStandardItem | None:
        """The tree item for the page or group titled ``title``, or ``None`` if nothing matches
        (#228, #230).

        A group's own title matches too, since #230 made a group row something `restore_selected_page`
        can show on its own (its stacked column), not just a stand-in for one of its pages.

        :param title: the title to look for.
        :returns: that row, or ``None``.
        """
        for row in range(self.__model.rowCount()):
            item = self.__model.item(row)
            if item is None:  # pragma: no cover  (a row within rowCount() always has an item)
                continue
            if item.text() == title:
                return item
            if item.data(PAGE_ROLE) is not None:
                continue
            for child_row in range(item.rowCount()):  # a page-less row is a group: its children are pages
                child = item.child(child_row)
                if child.text() == title:
                    return child
        return None

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

    def __current_pages(self) -> list[SettingsPage]:
        """The page(s) whose row is currently selected in the tree.

        :returns: a single-element list for a selected leaf page; every page under a selected group
            row, in tree order (#230); or an empty list if no row is selected.
        """
        if (item := self.__current_item()) is None:
            return []
        if (page := cast(SettingsPage | None, item.data(PAGE_ROLE))) is not None:
            return [page]
        return [cast(SettingsPage, item.child(row).data(PAGE_ROLE)) for row in range(item.rowCount())]

    def __shown_title(self) -> str | None:
        """The title of the page or group the stack is currently showing, or ``None`` while nothing
        is registered (#228, #230).

        Read off :attr:`__shown_row` rather than the widget in the stack, so it holds a title for the
        blank page too: what that blank stands in for is the row it will return to, which is what the
        next launch should restore (#230). Distinct from :meth:`__current_pages` (the tree's *selected*
        row): the two diverge whenever the live filter hides the shown row (#228).
        """
        return None if self.__shown_row is None else self.__shown_row.text()

    def __on_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        """Show the newly-selected row's page (or, for a group row, every page under it) in the stack.

        :param current: the newly-current tree index; unused directly (:meth:`__current_item` reads
            it back off the tree, keeping selection state in one place).
        :param previous: the previously-current tree index; unused.
        """
        del current, previous
        if (item := self.__current_item()) is not None:
            self.__show_row(item)

    def __apply_filter_to_current_page(self, *_args: object) -> None:
        """Re-run the frame-level filter on the currently-shown page(s).

        Called when the filter text or the "show full page if title matches" toggle changes, and
        when a different page (or group) becomes current -- so what's visible always reflects the
        live filter. A selected group shows every page under it stacked together (#230), so each of
        them is filtered in turn -- a filtered group view shows each page's matching frames.

        :param _args: the triggering signal's argument (filter text or toggle state); unused, the
            current values are read straight off the widgets.
        """
        del _args
        if (item := self.__current_item()) is not None:
            self.__apply_filter_to_row(item)

    def __apply_filter_to_row(self, item: QStandardItem) -> None:
        """Re-run the frame-level filter on ``item``'s page, or on every page under it if it's a group.

        Shared by :meth:`__apply_filter_to_current_page` (the tree-driven path) and
        :meth:`restore_selected_page` (which shows a row without going through tree selection, so it
        can't rely on that signal to filter what it just showed) (#230).

        :param item: a page row, or a group row.
        """
        if item.data(PAGE_ROLE) is not None:
            self.__apply_filter(item)
            return
        for row in range(item.rowCount()):
            self.__apply_filter(item.child(row))
        # which blocks survive is the filter's business; which headings that leaves standing is the
        # column's, and it can only be asked once every page under the group has been filtered
        self.__group_columns[item.text()].sync_headings()

    def __apply_filter(self, item: QStandardItem) -> None:
        """Re-run the block-level filter on ``item``'s page.

        Showing and hiding blocks is all there is to it, wherever those blocks currently are: the page's
        own view, or a group's column. Nothing has to be said here about headings or about a page
        emptied of every block -- a column heading follows the blocks under it
        (`SettingsBlockColumn.sync_headings`), and a page with nothing left to show contributes no
        blocks, so there is nothing of it in the column to take up room (#230).

        :param item: a page row -- never a group's: :meth:`__apply_filter_to_row` calls this once per
            child instead of once on the group itself, so a group's own pageless row (with no
            `FILTER_ROLE` of its own) never reaches here (#230).
        """
        frame_filter = cast(SettingsFrameFilter, item.data(FILTER_ROLE))
        frame_filter.apply(self.__ui.filter_edit.text(), self.__ui.show_full_page_check_box.is_checked())

    def __apply_all(self) -> None:
        """Apply every registered page's changes."""
        for page in self.__pages():
            page.save_changes()

    def __apply_current_page(self) -> None:
        """Apply the currently-selected row's changes -- one page, or every page under a group row."""
        for page in self.__current_pages():
            page.save_changes()

    def __reset_all(self) -> None:
        """Discard every registered page's in-progress changes."""
        for page in self.__pages():
            page.drop_changes()

    def __reset_current_page(self) -> None:
        """Discard the currently-selected row's changes -- one page, or every page under a group row."""
        for page in self.__current_pages():
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
