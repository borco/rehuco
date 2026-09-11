"""Files settings page: whether a deleted file goes through the Recycle Bin, and what a resource's
size scan and checksums leave out (#226, #291, #298)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import (
    BACKUP_SUFFIX,
    CHECKSUM_MANIFEST_EXTENSIONS,
    EXCLUDED_FILE_PATTERNS,
    IMAGE_EXTENSIONS,
    REHU_SUFFIX,
)

from ...item_action_icons import apply_item_action_icons
from ..excluded_files_settings import normalize_patterns, shared_excluded_files_settings
from ..persistent_settings import persistent_settings
from ..screenshot_deletion_settings import shared_screenshot_deletion_settings
from .files_page_ui import Ui_FilesPage

RECORD_PLACEHOLDER: Final = "<record>"
"""What stands in for a record's name in the structural exclusions shown on the page. Deliberately not
``info``: the rule covers *every* ``.rehu`` a scan meets -- the resource's own, a nested one's, a
file-scoped neighbour's -- so naming one would read as a literal and understate what is skipped."""


class FilesPage(QWidget):
    """Whether a deleted file goes through the Recycle Bin, and the filename globs left out of every
    directory-scoped resource's content scan (#226, #291, #298).

    Three frames for three settings. **Deleting files**, first, is the Recycle Bin choice
    (`ScreenshotDeletionSettings`) -- despite the name, it now covers a screenshot deleted from the
    images editor, a `.tc` conversion's discarded backup and a discarded conversion-backups set alike
    (#298), so it sits here rather than under "Images". The other two, unchanged since #226, are the
    two tiers of what a size scan and checksum run leave out: **Excluded file patterns** is the
    editable junk list, a `StringListEditor` (#231) wearing this app's icons. **Always excluded**,
    below it, is a read-only summary of the structural set -- every record a scan meets, with its
    screenshots and its checksum manifest, and the ``.orig`` backups a conversion keeps (#253), all
    derived inside core -- shown so the page tells the whole truth about what a scan skips, and not
    offered as list entries because those files change at any moment: counting one would make every
    size and checksum need recomputing after an ordinary metadata edit ([[data-model#checksums]]).

    Edits are staged in the widgets until :meth:`save_changes` pushes them into their own shared
    settings objects and persists them; from then on the excluded set is what the next size scan and
    the next checksum run are handed. Nothing re-measures on save -- a measurement is only ever filled
    by an explicit action -- so this page has no live-update wiring to drive beyond reloading its own
    editor.

    Saving the patterns normalizes: blanks and duplicates are dropped, and an emptied list resolves to
    the shipped defaults rather than to *no exclusions*. That rule lives in `ExcludedFilesSettings`,
    not in the editor, which holds whatever was typed; the page reloads itself from the saved result
    afterwards, so what it shows is always what a scan would actually use.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_FilesPage()
        self.__ui.setupUi(self)
        self.__ui.structural_patterns_label.setText(self.__structural_summary())
        self.__ui.patterns_editor.defaults = EXCLUDED_FILE_PATTERNS
        apply_item_action_icons(self.__ui.patterns_editor)

        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether either staged choice differs from what its own settings object currently holds.

        The staged patterns are normalized before the comparison, so a row that saving would drop
        anyway -- a blank insert, a duplicate -- is not yet a change (#53): while *Apply changes as
        they're made* is on, the dialog commits any dirty page, and a save here reloads the editor from
        what normalization kept, which would tear a freshly inserted row out from under its open cell.
        """
        return (
            self.__ui.use_recycle_bin_check_box.isChecked() != shared_screenshot_deletion_settings().use_recycle_bin
            or normalize_patterns(self.__ui.patterns_editor.values)
            != shared_excluded_files_settings().excluded_file_patterns
        )

    def save_changes(self) -> None:
        """Push every staged choice into its own settings object, persist it, and show the result.

        The pattern list is reloaded from the saved set afterwards rather than left as typed:
        normalization can change it -- a blank or duplicated entry is dropped, and emptying the list
        restores the shipped defaults -- and a page still showing what was typed would disagree with
        what every scan reads.
        """
        deletion = shared_screenshot_deletion_settings()
        deletion.use_recycle_bin = self.__ui.use_recycle_bin_check_box.isChecked()
        deletion.save(persistent_settings())

        excluded = shared_excluded_files_settings()
        excluded.patterns = normalize_patterns(self.__ui.patterns_editor.values)
        excluded.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard both staged choices, re-seeding each widget from its own settings object."""
        self.__ui.use_recycle_bin_check_box.setChecked(shared_screenshot_deletion_settings().use_recycle_bin)
        self.__ui.patterns_editor.values = shared_excluded_files_settings().excluded_file_patterns

    def __structural_summary(self) -> str:
        """Describe the four structural exclusions, written from the constants rather than restated.

        :returns: one line per exclusion, naming the record-derived shape and what it is.
        """
        screenshots = ", ".join(IMAGE_EXTENSIONS)
        manifests = ", ".join(CHECKSUM_MANIFEST_EXTENSIONS)
        return "\n".join(
            [
                f"{RECORD_PLACEHOLDER}{REHU_SUFFIX} — every resource record found while scanning",
                f"{RECORD_PLACEHOLDER}NN with {screenshots} — its screenshots",
                f"{RECORD_PLACEHOLDER} with {manifests} — its checksum manifest",
                f"anything ending in {BACKUP_SUFFIX} — the backups a conversion keeps",
            ]
        )
