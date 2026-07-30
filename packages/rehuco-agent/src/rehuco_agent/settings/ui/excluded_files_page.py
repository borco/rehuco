"""Excluded Files settings page: what a resource's size scan and checksums leave out (#226)."""

from collections.abc import Callable
from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QResizeEvent
from PySide6.QtWidgets import QListWidgetItem, QToolButton, QWidget
from rehuco_core import CHECKSUM_MANIFEST_EXTENSIONS, EXCLUDED_FILE_PATTERNS, IMAGE_EXTENSIONS, REHU_SUFFIX

from ..excluded_files_settings import normalize_patterns, shared_excluded_files_settings
from ..persistent_settings import persistent_settings
from .excluded_files_page_ui import Ui_ExcludedFilesPage

ADD_ICON_RESOURCE: Final = ":/icons/items_add.svg"
"""The action that appends the typed pattern to the list."""

EDIT_ICON_RESOURCE: Final = ":/icons/items_edit.svg"
"""The action that reopens the selected pattern for typing."""

REMOVE_ICON_RESOURCE: Final = ":/icons/items_delete.svg"
"""The action that drops the selected pattern."""

RESTORE_ICON_RESOURCE: Final = ":/icons/items_restore.svg"
"""The action that puts the shipped patterns back."""

ADD_TOOLTIP: Final = "Add the typed pattern to the list"
"""Names the add action; also how a test tells the row's buttons apart, since all four are icon-only."""

EDIT_TOOLTIP: Final = "Rename the selected pattern"
"""Names the edit action; see :data:`ADD_TOOLTIP`."""

REMOVE_TOOLTIP: Final = "Drop the selected pattern from the list"
"""Names the remove action; see :data:`ADD_TOOLTIP`."""

RESTORE_TOOLTIP: Final = "Replace the list with the patterns the app ships with"
"""Names the restore action; see :data:`ADD_TOOLTIP`."""

RECORD_PLACEHOLDER: Final = "<record>"
"""What stands in for a record's name in the structural exclusions shown on the page. Deliberately not
``info``: the rule covers *every* ``.rehu`` a scan meets -- the resource's own, a nested one's, a
file-scoped neighbour's -- so naming one would read as a literal and understate what is skipped."""


class ExcludedFilesPage(QWidget):
    """Edit the filename globs left out of every directory-scoped resource's content scan (#226).

    Two frames for the two tiers, because only one of them is the user's. **Always excluded** is a
    read-only summary of the structural set -- every record a scan meets, with its screenshots and its
    checksum manifest, all derived inside core -- shown so the page tells the whole truth about what a
    scan skips, and not offered as list entries because those files change at any moment: counting one
    would make every size and checksum need recomputing after an ordinary metadata edit
    ([[data-model#checksums]]). **Excluded file patterns** is the editable junk list.

    Edits are staged in the list widget until :meth:`save_changes` pushes them into the shared
    `ExcludedFilesSettings` and persists them; from then on that set is what the next size scan and the
    next checksum run are handed. Nothing re-measures on save -- a measurement is only ever filled by an
    explicit action -- so this page has no live-update wiring to drive.

    Saving normalizes: blanks and duplicates are dropped, and an emptied list resolves to the shipped
    defaults rather than to *no exclusions*. The list is reloaded from that result afterwards, so what the
    page shows is always what a scan would actually use.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ExcludedFilesPage()
        self.__ui.setupUi(self)
        self.__ui.structural_patterns_label.setText(self.__structural_summary())
        # the pattern list is what should take the slack when the page is tall, not the spacer
        self.__ui.main_layout.setStretch(1, 1)
        self.__declare_wrapped_heights()

        # the enabled state lives on the *action*, not the button: a QToolButton showing a default action
        # mirrors it, so disabling the button alone would be undone by the next action-driven refresh
        self.__add_action: Final = self.__bind(self.__ui.add_button, ADD_ICON_RESOURCE, ADD_TOOLTIP, self.__on_add)
        self.__edit_action: Final = self.__bind(self.__ui.edit_button, EDIT_ICON_RESOURCE, EDIT_TOOLTIP, self.__on_edit)
        self.__remove_action: Final = self.__bind(
            self.__ui.remove_button, REMOVE_ICON_RESOURCE, REMOVE_TOOLTIP, self.__on_remove
        )
        self.__bind(
            self.__ui.restore_defaults_button, RESTORE_ICON_RESOURCE, RESTORE_TOOLTIP, self.__on_restore_defaults
        )

        self.__ui.new_pattern_edit.textChanged.connect(self.__update_button_states)
        self.__ui.new_pattern_edit.returnPressed.connect(self.__on_add)
        self.__ui.patterns_list.currentRowChanged.connect(self.__update_button_states)

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Excluded Files"

    def is_dirty(self) -> bool:
        """Whether the staged pattern list differs from the set the shared settings resolve to."""
        return self.__staged_patterns() != shared_excluded_files_settings().excluded_file_patterns

    def save_changes(self) -> None:
        """Push the staged patterns into the shared settings object, persist them, and show the result.

        The list is reloaded from the saved set afterwards rather than left as typed: normalization can
        change it -- a blank or duplicated entry is dropped, and emptying the list restores the shipped
        defaults -- and a page still showing what was typed would disagree with what every scan reads.
        """
        settings = shared_excluded_files_settings()
        settings.patterns = normalize_patterns(self.__staged_patterns())
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, refilling the list from the shared settings' effective set."""
        self.__show_patterns(shared_excluded_files_settings().excluded_file_patterns)
        self.__ui.new_pattern_edit.clear()

    def __bind(self, button: QToolButton, icon: str, tooltip: str, slot: Callable[[], None]) -> QAction:
        """Drive one icon-only tool button from an action, kept theme-recolored.

        The same shape the field toolkit's action buttons take (#104, #198): a `QAction` set as the
        button's default action, its icon repainted by an
        :class:`~borco_pyside.theming.ActionIconThemeHandler`. The button's ``.ui`` text becomes the
        action's tooltip and nothing else, so the column reads as a row of item actions rather than a
        stack of sentences.

        :param button: the tool button declared in the ``.ui``.
        :param icon: the action's themed SVG resource path.
        :param tooltip: what the action does, in words -- the button is icon-only.
        :param slot: what to call when it fires.
        :returns: the action, parented here, and the place its enabled state lives.
        """
        action = QAction(self)
        action.setToolTip(tooltip)
        ActionIconThemeHandler(action, icon)
        action.triggered.connect(slot)
        button.setDefaultAction(action)
        return action

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt override)
        """Re-declare the wrapping notes' heights whenever the page's width changes.

        :param event: the Qt resize event.
        """
        super().resizeEvent(event)
        self.__declare_wrapped_heights()

    def __declare_wrapped_heights(self) -> None:
        """Give each wrapping note the minimum height its text actually needs at its current width.

        A word-wrapping `QLabel` knows its height only once it knows its width, and its ``sizeHint`` is
        computed as though it were laid out on one wide line -- so a frame sized from that hint is too
        short and the note paints past its border, which is what this page did. Setting
        ``heightForWidth`` on the size policy is the documented route and does not survive the trip
        through the enclosing frame here, so the height is **declared** instead: the same lesson #70 left
        behind, where a size hint never reached the dock and the fix was to state the height outright.

        The width is derived from the *page's* width, never read off the label or its frame: those are
        outputs of the very layout pass this feeds, so measuring them either ratchets the height upward
        forever or reads a width from before the resize. The page's width is an input -- the frames span
        it (the page layout has no margins), so the label's width is that less the frame's border and its
        layout's margins, and this settles in one pass.
        """
        for label, frame, layout in (
            (self.__ui.structural_note_label, self.__ui.structural_frame, self.__ui.structural_frame_layout),
            (self.__ui.patterns_note_label, self.__ui.patterns_frame, self.__ui.patterns_frame_layout),
        ):
            margins = layout.contentsMargins()
            width = self.width() - 2 * frame.frameWidth() - margins.left() - margins.right()
            if width > 0:
                label.setFixedHeight(label.heightForWidth(width))

    def __structural_summary(self) -> str:
        """Describe the three structural exclusions, written from the constants rather than restated.

        :returns: one line per exclusion, naming the record-derived shape and what it is.
        """
        screenshots = ", ".join(IMAGE_EXTENSIONS)
        manifests = ", ".join(CHECKSUM_MANIFEST_EXTENSIONS)
        return "\n".join(
            [
                f"{RECORD_PLACEHOLDER}{REHU_SUFFIX} — every resource record found while scanning",
                f"{RECORD_PLACEHOLDER}NN with {screenshots} — its screenshots",
                f"{RECORD_PLACEHOLDER} with {manifests} — its checksum manifest",
            ]
        )

    def __show_patterns(self, patterns: tuple[str, ...]) -> None:
        """Replace the list's contents with ``patterns``, each entry editable in place.

        :param patterns: the patterns to show, in order.
        """
        self.__ui.patterns_list.clear()
        for pattern in patterns:
            item = QListWidgetItem(pattern)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.__ui.patterns_list.addItem(item)
        self.__update_button_states()

    def __staged_patterns(self) -> tuple[str, ...]:
        """The pattern list as it currently stands on screen, unnormalized.

        :returns: every row's text, in order.
        """
        widget = self.__ui.patterns_list
        items = (widget.item(row) for row in range(widget.count()))
        return tuple(item.text() for item in items if item is not None)

    def __on_add(self) -> None:
        """Append the typed pattern to the list and clear the entry field."""
        pattern = self.__ui.new_pattern_edit.text().strip()
        if not self.__can_add(pattern):
            return
        item = QListWidgetItem(pattern)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.__ui.patterns_list.addItem(item)
        self.__ui.new_pattern_edit.clear()
        self.__ui.patterns_list.setCurrentItem(item)

    def __on_edit(self) -> None:
        """Open the selected row for in-place editing -- the same edit a double-click starts."""
        item = self.__ui.patterns_list.currentItem()
        if item is not None:
            self.__ui.patterns_list.editItem(item)

    def __on_remove(self) -> None:
        """Drop the selected row from the list."""
        row = self.__ui.patterns_list.currentRow()
        if row >= 0:
            self.__ui.patterns_list.takeItem(row)
            self.__update_button_states()

    def __on_restore_defaults(self) -> None:
        """Replace the staged list with the shipped defaults -- the only way back once it is emptied."""
        self.__show_patterns(EXCLUDED_FILE_PATTERNS)

    def __can_add(self, pattern: str) -> bool:
        """Whether ``pattern`` is worth adding: non-blank, and not already listed under any casing.

        :param pattern: the trimmed candidate.
        :returns: whether Add should do anything.
        """
        if not pattern:
            return False
        return pattern.lower() not in {existing.lower() for existing in self.__staged_patterns()}

    def __update_button_states(self) -> None:
        """Enable Add for a usable new pattern, and Edit/Remove only while a row is selected."""
        self.__add_action.setEnabled(self.__can_add(self.__ui.new_pattern_edit.text().strip()))
        has_selection = self.__ui.patterns_list.currentItem() is not None
        self.__edit_action.setEnabled(has_selection)
        self.__remove_action.setEnabled(has_selection)
