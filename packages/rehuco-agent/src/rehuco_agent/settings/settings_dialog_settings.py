"""The SettingsDialog's own filter state, persisted across restarts (#76), and its last-shown page (#228)."""

from dataclasses import dataclass, field
from typing import Final, cast

from PySide6.QtCore import QSettings

GROUP: Final = "settings_dialog"
FILTER_TEXT_KEY: Final = "filter_text"
SHOW_FULL_PAGE_KEY: Final = "show_full_page_on_title_match"
SHOW_FULL_GROUP_KEY: Final = "show_full_group_on_title_match"
SELECTED_PAGE_KEY: Final = "selected_page_title"


@dataclass
class SettingsDialogSettings:
    """The settings dialog's filter text, its two "show full ... if title matches" toggles, and the
    title of the page it was last showing (#228)."""

    filter_text: str = field(default="")
    """The text in the filter box, restored so a search survives a restart; empty shows every page."""

    show_full_page_on_title_match: bool = field(default=False)
    """Whether text matching a page's title shows that page's every frame ([[appendices.settings-pages]])."""

    show_full_group_on_title_match: bool = field(default=False)
    """Whether text matching a group's title shows every page under it
    ([[appendices.settings-pages#category-groups]])."""

    selected_page_title: str = field(default="")
    """The title of the page shown when the dialog was last closed. Stored by title rather than tree
    position: the tree's rows differ per platform and shift whenever a page or group is added, so a
    stored index would silently select a different page than the one that was showing (#228)."""

    def load(self, settings: QSettings) -> None:
        """Replace the current filter text, toggle states and selected-page title with what's in
        persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.filter_text = cast(str, settings.value(FILTER_TEXT_KEY, "", type=str))
        self.show_full_page_on_title_match = cast(bool, settings.value(SHOW_FULL_PAGE_KEY, False, type=bool))
        self.show_full_group_on_title_match = cast(bool, settings.value(SHOW_FULL_GROUP_KEY, False, type=bool))
        self.selected_page_title = cast(str, settings.value(SELECTED_PAGE_KEY, "", type=str))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the filter text, toggle states and selected-page title to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(FILTER_TEXT_KEY, self.filter_text)
        settings.setValue(SHOW_FULL_PAGE_KEY, self.show_full_page_on_title_match)
        settings.setValue(SHOW_FULL_GROUP_KEY, self.show_full_group_on_title_match)
        settings.setValue(SELECTED_PAGE_KEY, self.selected_page_title)
        settings.endGroup()
