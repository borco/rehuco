"""What the Shortcuts settings page remembers about how it was being looked at: its search text and the
column its table was sorted by (#344)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QSettings, Qt

GROUP: Final = "shortcuts_page"
FILTER_TEXT_KEY: Final = "filter_text"
SORT_COLUMN_KEY: Final = "sort_column"
SORT_DESCENDING_KEY: Final = "sort_descending"

UNSORTED: Final = -1
"""The sort column meaning "the order the commands were declared in"."""


@dataclass
class ShortcutsPageSettings:
    """The Shortcuts page's search text and table sort -- view state, not settings the page applies, so it
    is written as soon as it changes rather than waiting for Apply.

    Owned by the page, loaded and saved directly, the shape
    :class:`~rehuco_agent.settings.conversion_backups_dialog_settings.ConversionBackupsDialogSettings`
    follows: nothing else reads it.
    """

    filter_text: str = field(default="")
    """The search box's text; empty shows every command."""

    sort_column: int = field(default=UNSORTED)
    """The column the table is sorted by, or :data:`UNSORTED`."""

    sort_order: Qt.SortOrder = field(default=Qt.SortOrder.AscendingOrder)
    """The direction of the sort."""

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.filter_text = cast(str, settings.value(FILTER_TEXT_KEY, "", type=str))
        self.sort_column = cast(int, settings.value(SORT_COLUMN_KEY, UNSORTED, type=int))
        descending = cast(bool, settings.value(SORT_DESCENDING_KEY, False, type=bool))
        self.sort_order = Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Write the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(FILTER_TEXT_KEY, self.filter_text)
        settings.setValue(SORT_COLUMN_KEY, self.sort_column)
        settings.setValue(SORT_DESCENDING_KEY, self.sort_order == Qt.SortOrder.DescendingOrder)
        settings.endGroup()
