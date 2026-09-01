"""Legacy Screenshots settings page: how a `.tc`'s screenshots are recognized when it is converted
([[acquisition-tooling#screenshot-schemes]], #53).
"""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import LEGACY_SCREENSHOT_RULES

from ..legacy_screenshots_settings import (
    normalize_legacy_screenshot_rules,
    shared_legacy_screenshots_settings,
)
from ..persistent_settings import persistent_settings
from .legacy_screenshots_page_ui import Ui_LegacyScreenshotsPage


class LegacyScreenshotsPage(QWidget):
    """Edit the naming rules a legacy `.tc`'s screenshots are recognized by (#53).

    Two frames, for the same reason `ExcludedFilesPage` has two: only one of them is the user's.
    **Legacy screenshot rules** is the editable list, a
    :class:`~rehuco_agent.settings.ui.legacy_screenshot_rules_editor.LegacyScreenshotRulesEditor` whose
    two columns are a series' cover and the template for the files after it. **Always applied** is a
    read-only statement of the tie-break -- largest pixel size, then `.jpg`/`.jpeg`, then first by name
    -- shown so the page tells the whole truth about how a screenshot is chosen, and not offered as
    settings because it applies whatever the rules say.

    **The ordering column stays visible**, unlike a list whose order is presentation: the first rule
    whose cover is present in a folder claims that folder, so moving a rule changes what a conversion
    does. Two rules sharing a template and differing only in their cover -- an ``image-00``-first series
    and an ``image-01``-first one -- are told apart by nothing else.

    Edits are staged in the editor until :meth:`save_changes` pushes them into the shared
    `LegacyScreenshotsSettings` and persists them; from then on that set is what the next conversion,
    the next dry run and the next content walk are handed. Nothing re-scans on save -- a conversion is
    only ever started explicitly -- so this page has no live-update wiring to drive.

    Saving normalizes: blank and uncompilable rules are dropped, duplicates go, and an emptied list
    resolves to the shipped defaults rather than to *recognize nothing*. That rule lives in
    `LegacyScreenshotsSettings`, not in the editor, which holds whatever was typed; the page reloads
    itself from the saved result afterwards, so what it shows is always what a scan would actually use.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_LegacyScreenshotsPage()
        self.__ui.setupUi(self)
        self.__ui.rules_editor.defaults = LEGACY_SCREENSHOT_RULES

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Legacy Screenshots"

    def is_dirty(self) -> bool:
        """Whether applying would change the set the shared settings resolve to.

        The staged rules are normalized before the comparison, so a row that saving would drop anyway --
        blank, half-typed, uncompilable -- is not yet a change. That is what lets an insert survive
        while *Apply changes as they're made* is on: the dialog polls this and commits a dirty page,
        and a save here reloads the editor from what normalization kept, which would tear the fresh
        row out from under its open cell (#53).
        """
        staged = normalize_legacy_screenshot_rules(self.__ui.rules_editor.values)
        return staged != shared_legacy_screenshots_settings().legacy_screenshot_rules

    def save_changes(self) -> None:
        """Push the staged rules into the shared settings object, persist them, and show the result.

        The list is reloaded from the saved set afterwards rather than left as typed: normalization can
        change it -- a blank or uncompilable rule is dropped, and emptying the list restores the shipped
        defaults -- and a page still showing what was typed would disagree with what every scan reads.
        """
        settings = shared_legacy_screenshots_settings()
        settings.rules = normalize_legacy_screenshot_rules(self.__ui.rules_editor.values)
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, refilling the editor from the shared settings' effective set."""
        self.__ui.rules_editor.values = shared_legacy_screenshots_settings().legacy_screenshot_rules
