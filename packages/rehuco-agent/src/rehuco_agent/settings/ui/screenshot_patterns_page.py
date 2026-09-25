"""Images / Sidecar Names settings page: the name patterns a resource's sidecar images are
recognized by, first written for how a `.tc`'s screenshots are recognized when it is converted
([[acquisition-tooling#screenshot-schemes]], #53, #287).
"""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePattern

from ..persistent_settings import persistent_settings
from ..screenshot_patterns_settings import (
    DEFAULT_SAMPLES,
    ScreenshotPatternsSettings,
    normalize_screenshot_name_patterns,
    normalize_screenshot_samples,
    shared_screenshot_patterns_settings,
)
from .screenshot_patterns_page_ui import Ui_ScreenshotPatternsPage


class ScreenshotPatternsPage(QWidget):
    """Edit the naming patterns a legacy `.tc`'s screenshots are recognized by (#53, #287).

    Three frames. **Screenshot name patterns** is the editable list, a
    :class:`~rehuco_agent.settings.ui.screenshot_name_patterns_editor.ScreenshotNamePatternsEditor` of
    one column each: an ordinary regular expression, matched case-insensitively against a filename's
    stem. **Always applied** is a read-only statement of what a conversion does with the slots the
    patterns name -- the earlier pattern takes a contested one, several extensions of one name resolve
    by pixel size, and every other image keeps its own name (#288) -- shown so the page tells the whole
    truth, and not offered as a setting because it applies whatever the patterns say. **Try it** is a
    :class:`~rehuco_agent.settings.ui.screenshot_try_it_editor.ScreenshotTryItEditor`: a sample filename
    beside the slot the patterns above would assign it, refreshed on every edit to the pattern list
    (#287) -- so a pattern edit shows its effect on the catalog's actual names rather than only on the
    regex itself.

    **The samples are a setting like the patterns**: staged in the table, part of :meth:`is_dirty`, saved
    by :meth:`save_changes`, put back by :meth:`drop_changes` and :meth:`seed_defaults` -- so their frame
    dirties, and takes Apply, Reset, Defaults and "Apply changes as they're made", the way every other
    frame does. The slot beside each never waits for any of that: it is derived from the sample as
    typed and the patterns as staged.

    **The ordering column stays visible**, unlike a list whose order is presentation: patterns are tried
    top to bottom and the first match wins, so moving a pattern can change which one claims a name that
    more than one would otherwise match -- and which of two images takes a number they both want.

    Edits are staged in the editor until :meth:`save_changes` pushes them into the shared
    `ScreenshotPatternsSettings` and persists them; from then on that set is what the next conversion,
    the next dry run and the next content walk are handed. Nothing re-scans on save -- a conversion is
    only ever started explicitly -- so this page has no live-update wiring to drive beyond the try-it
    table refreshing itself from the staged (not yet saved) patterns.

    Saving normalizes: blank patterns and exact duplicates go, and an emptied list resolves to the
    shipped defaults rather than to *recognize nothing* -- but an **uncompilable row is kept**, flagged,
    so a typo is fixed in place rather than retyped (#322): only the effective set a scan reads skips it.
    That rule lives in `ScreenshotPatternsSettings`, not in the editor, which holds whatever was typed;
    the page reloads itself from the stored result afterwards, so what it shows is always what the next
    Apply would keep.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ScreenshotPatternsPage()
        self.__ui.setupUi(self)
        self.__ui.patterns_editor.defaults = SCREENSHOT_NAME_PATTERNS
        self.__ui.try_it_editor.defaults = DEFAULT_SAMPLES
        # the try-it table reads the patterns editor's live (unsaved) values, so an edit above shows its
        # effect immediately rather than only after Save
        self.__ui.try_it_editor.patterns_provider = lambda: self.__ui.patterns_editor.values
        self.__ui.patterns_editor.values_changed.connect(self.__ui.try_it_editor.refresh_slots)

        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether applying would change the stored patterns or try-it samples.

        Both are normalized before the comparison, so a row that saving would drop anyway -- blank, or an
        exact repeat pattern -- is not yet a change. That is what lets an insert survive while *Apply
        changes as they're made* is on: the dialog polls this and commits a dirty page, and a save here
        reloads both editors from what normalization kept, which would tear the fresh row out from under
        its open cell (#53). An uncompilable pattern *is* a change, since saving keeps it.
        """
        settings = shared_screenshot_patterns_settings()
        staged = tuple(pattern.pattern for pattern in self.__ui.patterns_editor.values)
        return (
            normalize_screenshot_name_patterns(staged) != settings.stored_patterns
            or normalize_screenshot_samples(self.__ui.try_it_editor.values) != settings.samples
        )

    def save_changes(self) -> None:
        """Push the staged patterns and try-it samples into the shared settings object, persist them,
        and show the result.

        Both are reloaded from what was stored afterwards rather than left as typed: normalization can
        change them -- a blank row is dropped, and emptying a list restores the shipped one -- and a page
        still showing what was typed would disagree with what the next Apply would keep.
        """
        settings = shared_screenshot_patterns_settings()
        staged = tuple(pattern.pattern for pattern in self.__ui.patterns_editor.values)
        settings.patterns = normalize_screenshot_name_patterns(staged)
        settings.samples = normalize_screenshot_samples(self.__ui.try_it_editor.values)
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, refilling the patterns editor from the shared settings' stored set --
        uncompilable rows included, flagged -- and the try-it table from the stored samples."""
        self.__show(shared_screenshot_patterns_settings())

    def seed_defaults(self) -> None:
        """Stage the factory state: the patterns an unloaded `ScreenshotPatternsSettings` resolves to --
        the shipped `SCREENSHOT_NAME_PATTERNS` -- and the shipped try-it samples (#342)."""
        self.__show(ScreenshotPatternsSettings())

    def __show(self, settings: ScreenshotPatternsSettings) -> None:
        """Refill the patterns editor from ``settings``' stored set and the try-it table from its
        samples, and re-derive the try-it slots.

        :param settings: the shared object's saved state, or a fresh one's defaults.
        """
        stored = settings.stored_patterns
        self.__ui.patterns_editor.values = tuple(ScreenshotNamePattern(pattern) for pattern in stored)
        self.__ui.try_it_editor.values = settings.samples
        self.__ui.try_it_editor.refresh_slots()
