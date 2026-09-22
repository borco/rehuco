"""Files settings page: how a deleted file is deleted and whether that is asked about, and what a
resource's size scan and checksums leave out (#226, #291, #298, #312)."""

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
from ..deletion_settings import DeletionSettings, shared_deletion_settings
from ..excluded_files_settings import ExcludedFilesSettings, normalize_patterns, shared_excluded_files_settings
from ..persistent_settings import persistent_settings
from .files_page_ui import Ui_FilesPage

RECORD_PLACEHOLDER: Final = "<record>"
"""What stands in for a record's name in the structural exclusions shown on the page. Deliberately not
``info``: the rule covers *every* ``.rehu`` a scan meets -- the resource's own, a nested one's, a
file-scoped neighbour's -- so naming one would read as a literal and understate what is skipped."""


class FilesPage(QWidget):
    """How a deleted file is deleted and whether that is asked about, and the filename globs left out
    of every directory-scoped resource's content scan (#226, #291, #298, #312).

    Three frames for three settings. **Deleting files**, first, is the one deletion policy
    (`DeletionSettings`): *Move deleted files to the Recycle Bin, if possible* first, then -- under a
    caption saying a permanent delete is confirmed unless -- *Clear backups without asking* and
    *Delete images without asking*. That order is the dependency: the bin box decides whether a delete
    is permanent from the start (off) or only when no bin is reachable (on), and a question is only
    ever asked for a permanent delete, so the two boxes under the caption only ever matter once the
    first has made one. It covers a screenshot deleted from the images editor, a `.tc` conversion's discarded backup
    and a discarded conversion-backups set alike (#298), so it sits here rather than under "Images".
    The other two frames, unchanged since #226, are the
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
        deletion = shared_deletion_settings()
        return (
            self.__ui.clear_backups_without_asking_check_box.isChecked() != deletion.clear_backups_without_asking
            or self.__ui.delete_images_without_asking_check_box.isChecked() != deletion.delete_images_without_asking
            or self.__ui.use_recycle_bin_check_box.isChecked() != deletion.use_recycle_bin
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
        deletion = shared_deletion_settings()
        deletion.clear_backups_without_asking = self.__ui.clear_backups_without_asking_check_box.isChecked()
        deletion.delete_images_without_asking = self.__ui.delete_images_without_asking_check_box.isChecked()
        deletion.use_recycle_bin = self.__ui.use_recycle_bin_check_box.isChecked()
        deletion.save(persistent_settings())

        excluded = shared_excluded_files_settings()
        excluded.patterns = normalize_patterns(self.__ui.patterns_editor.values)
        excluded.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard both staged choices, re-seeding each widget from its own settings object."""
        self.__show(shared_deletion_settings(), shared_excluded_files_settings())

    def seed_defaults(self) -> None:
        """Stage the factory values: what unloaded `DeletionSettings` and `ExcludedFilesSettings`
        hold (#342)."""
        self.__show(DeletionSettings(), ExcludedFilesSettings())

    def __show(self, deletion: DeletionSettings, excluded: ExcludedFilesSettings) -> None:
        """Fill every widget from the two settings objects.

        :param deletion: the deletion choices to show.
        :param excluded: the excluded-patterns list to show, as it resolves.
        """
        self.__ui.clear_backups_without_asking_check_box.setChecked(deletion.clear_backups_without_asking)
        self.__ui.delete_images_without_asking_check_box.setChecked(deletion.delete_images_without_asking)
        self.__ui.use_recycle_bin_check_box.setChecked(deletion.use_recycle_bin)
        self.__ui.patterns_editor.values = excluded.excluded_file_patterns

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
