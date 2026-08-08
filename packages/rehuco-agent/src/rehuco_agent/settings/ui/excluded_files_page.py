"""Excluded Files settings page: what a resource's size scan and checksums leave out (#226)."""

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
from .excluded_files_page_ui import Ui_ExcludedFilesPage

RECORD_PLACEHOLDER: Final = "<record>"
"""What stands in for a record's name in the structural exclusions shown on the page. Deliberately not
``info``: the rule covers *every* ``.rehu`` a scan meets -- the resource's own, a nested one's, a
file-scoped neighbour's -- so naming one would read as a literal and understate what is skipped."""


class ExcludedFilesPage(QWidget):
    """Edit the filename globs left out of every directory-scoped resource's content scan (#226).

    Two frames for the two tiers, because only one of them is the user's. **Always excluded** is a
    read-only summary of the structural set -- every record a scan meets, with its screenshots and its
    checksum manifest, and the ``.orig`` backups a conversion keeps (#253), all derived inside core --
    shown so the page tells the whole truth about what a
    scan skips, and not offered as list entries because those files change at any moment: counting one
    would make every size and checksum need recomputing after an ordinary metadata edit
    ([[data-model#checksums]]). A backup is there for the other reason (#253): it is not the resource's
    content, and counting it would put it in a baseline that a later discard then reports as a missing
    file. **Excluded file patterns** is the editable junk list, a
    `StringListEditor` (#231) wearing this app's icons.

    Edits are staged in the editor until :meth:`save_changes` pushes them into the shared
    `ExcludedFilesSettings` and persists them; from then on that set is what the next size scan and the
    next checksum run are handed. Nothing re-measures on save -- a measurement is only ever filled by an
    explicit action -- so this page has no live-update wiring to drive.

    Saving normalizes: blanks and duplicates are dropped, and an emptied list resolves to the shipped
    defaults rather than to *no exclusions*. That rule lives in `ExcludedFilesSettings`, not in the
    editor, which holds whatever was typed; the page reloads itself from the saved result afterwards, so
    what it shows is always what a scan would actually use.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ExcludedFilesPage()
        self.__ui.setupUi(self)
        self.__ui.structural_patterns_label.setText(self.__structural_summary())
        self.__ui.patterns_editor.defaults = EXCLUDED_FILE_PATTERNS
        apply_item_action_icons(self.__ui.patterns_editor)

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Excluded Files"

    def is_dirty(self) -> bool:
        """Whether the staged pattern list differs from the set the shared settings resolve to."""
        return self.__ui.patterns_editor.values != shared_excluded_files_settings().excluded_file_patterns

    def save_changes(self) -> None:
        """Push the staged patterns into the shared settings object, persist them, and show the result.

        The list is reloaded from the saved set afterwards rather than left as typed: normalization can
        change it -- a blank or duplicated entry is dropped, and emptying the list restores the shipped
        defaults -- and a page still showing what was typed would disagree with what every scan reads.
        """
        settings = shared_excluded_files_settings()
        settings.patterns = normalize_patterns(self.__ui.patterns_editor.values)
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, refilling the editor from the shared settings' effective set."""
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
