"""The category tree's filter, and the item-data roles each of its rows carries (#47, #76, #277, #475)."""

from typing import Final, cast, override

from borco_core import TextMatcher
from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel

from .settings_frame_filter import SettingsFrameFilter

PAGE_ROLE: Final = Qt.ItemDataRole.UserRole + 1
"""Item-data role storing each category-tree row's page widget, for selection-driven page switching."""

FILTER_ROLE: Final = Qt.ItemDataRole.UserRole + 2
"""Item-data role storing each row's `SettingsFrameFilter`, for page- and frame-level filtering."""

TITLE_ROLE: Final = Qt.ItemDataRole.UserRole + 3
"""Item-data role storing each row's title -- a page's or a group's -- as `add_page` was given it (#277).

**A row's identity, kept apart from what it displays.** The display text carries the dirty badge (#77),
so everything that has to recognize a row rather than draw it (`restore_selected_page`,
`save_filter_state`, the tree filter, a group column's headings) reads this instead of unpicking a
prefix from the text."""


class CategoryFilterProxyModel(QSortFilterProxyModel):
    """Shows only rows whose page title and frame texts match the filter text: every word of it found in one
    of them, a quoted run as one phrase, case and accents ignored (:class:`~borco_core.TextMatcher`, #475).

    Matched in Python against the row's `SettingsFrameFilter`, not through Qt's own
    ``setFilterFixedString``/``filterRegularExpression``, which match one pattern against one column.

    Group rows carry no page: one is shown exactly when at least one of its pages is (#76). Qt
    hides a rejected parent's whole subtree, so a group must accept on its children's behalf --
    it can never be shown "empty", and a page can never be hidden by its group alone.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__matcher = TextMatcher()
        self.__show_full_group = False

    def set_filter_text(self, text: str) -> None:
        """Update the filter text and re-evaluate every row.

        :param text: the text to match page titles/field labels against, as every search box does
            (:class:`~borco_core.TextMatcher`, #475).
        """
        self.__matcher = TextMatcher.of(text)
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
        if not self.__matcher:
            return True
        model = cast(QStandardItemModel, self.sourceModel())
        item = model.itemFromIndex(model.index(source_row, 0, source_parent))
        if item.data(PAGE_ROLE) is not None:
            return self.__accepts_page(item)
        return any(self.__accepts_page(item.child(row)) for row in range(item.rowCount()))

    def __accepts_page(self, item: QStandardItem) -> bool:
        """Whether ``item``'s page is shown: every word of the filter is in its own title or a frame's text,
        or -- with "show full group if title matches" on -- its group's title matches.

        :param item: the page's source-model row.
        :returns: whether the page should be shown.
        """
        title = cast(str, item.data(TITLE_ROLE))
        frame_filter = cast(SettingsFrameFilter, item.data(FILTER_ROLE))
        if self.__matcher.matches(title, *frame_filter.field_labels()):
            return True
        group = item.parent()
        if group is None:
            return False
        return self.__show_full_group and self.__matcher.matches(cast(str, group.data(TITLE_ROLE)))
