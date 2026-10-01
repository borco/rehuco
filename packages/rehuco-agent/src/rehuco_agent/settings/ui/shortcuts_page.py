"""Shortcuts settings page: every command, its keys and its scope, edited as a draft keymap (#344)."""

from collections.abc import Sequence
from typing import Final

from borco_pyside.shortcuts import Command, CommandRegistry, CommandScope, Keymap, find_conflicts, keys_text
from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QHeaderView, QMessageBox, QWidget

from ..persistent_settings import persistent_settings
from ..shortcuts_page_settings import ShortcutsPageSettings
from ..shortcuts_settings import shared_shortcuts_settings
from .key_list_editor import NEW_KEY
from .settings_frame_header import SettingsFrameHeader
from .shortcuts_page_ui import Ui_ShortcutsPage
from .shortcuts_table_model import (
    COMMAND_COLUMN,
    COMMAND_ID_ROLE,
    CONFLICT_COLUMN,
    KEYS_COLUMN,
    SCOPE_COLUMN,
    ShortcutsFilterProxyModel,
    ShortcutsTableModel,
)

NO_SELECTION_TITLE: Final = "Select a command"
"""The editor's title while no command is selected."""

NO_KEYS_TEXT: Final = "None"
"""What the Default line reads for a command declared without keys."""

TABLE_FRAME_INDEX: Final = 0
"""The table frame's position in the page's root layout -- the block that fills the page."""


class ShortcutsPage(QWidget):
    """Edit the keymap: which keys fire each command, and where they reach.

    The table lists every command and fills the page; the editor beneath it, always in view, edits the
    selected one -- its scope, and its keys as buttons that record a replacement when clicked. The page
    works on a **draft** of the keymap (the table model holds it); nothing reaches the registry until a
    save, which writes the overrides to the settings and hands them to the registry, so open documents
    pick the keys up at once.

    **A conflict is asked about when it is made.** Every edit of one command -- a recorded key, a scope
    picked, its own Reset or Defaults -- is checked against the other commands first, and one that would
    take another command's key asks to reassign it (removing it there) or to cancel. The Conflict column and
    `~.settings_page.SaveGatedPage`'s :meth:`can_save` remain, as the net under a path that skipped the ask.

    **Two levels of Apply / Reset / Defaults.** The toolbar's and the table frame's act on the whole draft:
    the table is a value control (`~.shortcuts_table_view.ShortcutsTableView`), so the dialog's generic path
    restores and commits it. The editor's own header acts on the selected command alone -- its Apply saves
    that command (and any command it took a key from) on top of what is saved, leaving the rest of the
    draft staged.

    :param registry: the commands to edit.
    :param parent: optional Qt parent.
    """

    def __init__(self, registry: CommandRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__registry: Final = registry
        self.__ui: Final = Ui_ShortcutsPage()
        self.__ui.setupUi(self)
        self.__ui.main_layout.setStretch(TABLE_FRAME_INDEX, 1)
        self.__model: Final = ShortcutsTableModel(registry, self)
        self.__proxy: Final = ShortcutsFilterProxyModel(self)
        self.__proxy.setSourceModel(self.__model)
        self.__filling = False
        """Whether the editor is being filled from the draft, which must not write back to it."""

        table = self.__ui.shortcuts_table
        table.setModel(self.__proxy)
        table.setItemDelegate(RowBandDelegate(self))
        header = table.horizontalHeader()
        header.setSectionResizeMode(COMMAND_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(KEYS_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(SCOPE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(CONFLICT_COLUMN, QHeaderView.ResizeMode.ResizeToContents)

        # how the table was being looked at -- search text and sort -- comes back as it was left
        self.__view_settings: Final = ShortcutsPageSettings()
        self.__view_settings.load(persistent_settings())
        self.__ui.search_edit.setText(self.__view_settings.filter_text)
        self.__proxy.set_filter_text(self.__view_settings.filter_text)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self.__view_settings.sort_column, self.__view_settings.sort_order)
        table.setSortingEnabled(True)

        # the editor's own Apply / Reset / Defaults, acting on the selected command alone; the dialog builds
        # none here, since every control in this frame is scratch
        self.__editor_header: Final = SettingsFrameHeader(self.__ui.selected_frame_label)
        self.__editor_header.apply_action.setToolTip("Apply this command's change")
        self.__editor_header.reset_action.setToolTip("Reset this command to its saved keys")
        self.__editor_header.defaults_action.setToolTip("Restore this command's default keys")
        self.__editor_header.apply_action.triggered.connect(self.__apply_selected)
        self.__editor_header.reset_action.triggered.connect(self.__reset_selected)
        self.__editor_header.defaults_action.triggered.connect(self.__restore_selected_defaults)

        self.__ui.search_edit.textChanged.connect(self.__on_search_changed)
        header.sortIndicatorChanged.connect(self.__on_sort_changed)
        table.selectionModel().currentRowChanged.connect(self.__on_current_row_changed)
        self.__ui.scope_combo.activated.connect(self.__on_scope_activated)
        self.__ui.keys_editor.key_recorded.connect(self.__on_key_recorded)
        self.__ui.keys_editor.key_removed.connect(self.__on_key_removed)
        self.__model.draft_replaced.connect(self.__show_selected)
        self.__model.dataChanged.connect(self.__refresh_editor_header)
        self.drop_changes()
        if self.__proxy.rowCount():
            table.selectRow(0)

    @property
    def editor_header(self) -> SettingsFrameHeader:
        """The selected command's own Apply / Reset / Defaults row."""
        return self.__editor_header

    def is_dirty(self) -> bool:
        """Whether the draft differs from the saved keymap."""
        return self.__model.draft() != shared_shortcuts_settings().keymap

    def can_save(self) -> bool:
        """Whether the draft may be saved: no two commands collide."""
        return not self.__model.has_conflicts()

    def save_changes(self) -> None:
        """Persist the draft's overrides and put them in force. Refuses while :meth:`can_save` is false."""
        if self.can_save():
            self.__save(self.__model.draft())

    def drop_changes(self) -> None:
        """Discard the draft, showing the saved keymap."""
        self.__model.set_draft(shared_shortcuts_settings().keymap)

    def seed_defaults(self) -> None:
        """Stage the factory keymap: no override at all."""
        self.__model.set_draft(Keymap())

    def __save(self, keymap: Keymap) -> None:
        """Write ``keymap`` to the settings and put it in force.

        :param keymap: the overrides to save.
        """
        settings = shared_shortcuts_settings()
        settings.keymap = keymap.copy()
        settings.save(persistent_settings())
        self.__registry.set_keymap(settings.keymap)
        self.__refresh_editor_header()

    # region view state

    def __on_search_changed(self, text: str) -> None:
        """Narrow the table to ``text``, and remember it.

        :param text: the search text.
        """
        self.__proxy.set_filter_text(text)
        self.__view_settings.filter_text = text
        self.__view_settings.save(persistent_settings())

    def __on_sort_changed(self, column: int, order: Qt.SortOrder) -> None:
        """Remember the column the table was sorted by.

        :param column: the sort column.
        :param order: its direction.
        """
        self.__view_settings.sort_column = column
        self.__view_settings.sort_order = order
        self.__view_settings.save(persistent_settings())

    # endregion

    # region the selected command

    def __selected_command(self) -> Command | None:
        """The command the table's current row shows, or ``None`` while nothing is current."""
        index = self.__ui.shortcuts_table.currentIndex()
        if not index.isValid():
            return None
        return self.__registry.command(str(index.data(COMMAND_ID_ROLE)))

    def __on_current_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Follow the selection: show its command in the editor.

        :param current: the new current row.
        """
        del current
        self.__show_selected()

    def __show_selected(self) -> None:
        """Fill the editor from the draft's view of the selected command."""
        command = self.__selected_command()
        self.__ui.selected_frame.setEnabled(command is not None)
        self.__filling = True
        try:
            combo = self.__ui.scope_combo
            combo.clear()
            if command is None:
                self.__ui.selected_frame_label.setText(NO_SELECTION_TITLE)
                self.__ui.default_keys_label.setText(NO_KEYS_TEXT)
                self.__ui.keys_editor.set_keys(())
            else:
                self.__ui.selected_frame_label.setText(f"{command.name} — {command.description}")
                for scope in command.scopes:
                    combo.addItem(scope.label, scope)
                    combo.setItemData(combo.count() - 1, scope.hint, Qt.ItemDataRole.ToolTipRole)
                combo.setCurrentIndex(command.scopes.index(self.__model.scope_of(command.id)))
                combo.setEnabled(len(command.scopes) > 1)
                defaults = command.default_key_sequences()
                self.__ui.default_keys_label.setText(
                    "; ".join(keys_text([key]) for key in defaults) if defaults else NO_KEYS_TEXT
                )
                self.__ui.keys_editor.set_keys(self.__model.keys_of(command.id))
        finally:
            self.__filling = False
        self.__refresh_editor_header()

    def __on_scope_activated(self, index: int) -> None:
        """Move the selected command to the scope picked, asking first if that makes it collide.

        :param index: the combo row picked.
        """
        command = self.__selected_command()
        if self.__filling or command is None:
            return
        if not self.__change(command, self.__model.keys_of(command.id), command.scopes[index]):
            self.__show_selected()  # cancelled: put the combo back

    def __on_key_recorded(self, index: int, sequence: QKeySequence) -> None:
        """Replace the key at ``index`` with ``sequence``, or add it, asking first if that collides.

        :param index: the key replaced, or `NEW_KEY`.
        :param sequence: the key recorded.
        """
        command = self.__selected_command()
        if command is None:
            return
        keys = list(self.__model.keys_of(command.id))
        if index == NEW_KEY:
            keys.append(sequence)
        else:
            keys[index] = sequence
        self.__change(command, keys, self.__model.scope_of(command.id))

    def __on_key_removed(self, index: int) -> None:
        """Remove the key at ``index`` -- never a conflict, so never asked about.

        :param index: the key's position.
        """
        command = self.__selected_command()
        if command is None:
            return
        keys = [key for at, key in enumerate(self.__model.keys_of(command.id)) if at != index]
        self.__model.set_entry(command.id, keys, self.__model.scope_of(command.id))
        self.__show_selected()

    def __apply_selected(self) -> None:
        """Save the selected command's draft entry alone, on top of what is saved."""
        command = self.__selected_command()
        if command is None:
            return
        merged = self.__model.committed_with(shared_shortcuts_settings().keymap, command.id)
        if not find_conflicts(self.__registry.commands(), merged):
            self.__save(merged)

    def __reset_selected(self) -> None:
        """Put the selected command back to its saved keys and scope, asking first if that collides."""
        command = self.__selected_command()
        if command is not None:
            saved = shared_shortcuts_settings().keymap
            self.__change(command, saved.effective_keys(command), saved.effective_scope(command))

    def __restore_selected_defaults(self) -> None:
        """Put the selected command back to its declared keys and scope, asking first if that collides."""
        command = self.__selected_command()
        if command is not None:
            self.__change(command, command.default_key_sequences(), command.default_scope)

    def __change(self, command: Command, keys: Sequence[QKeySequence], scope: CommandScope) -> bool:
        """Give ``command`` ``keys`` in ``scope`` -- taking any colliding key from the other commands once the
        user agrees -- and show the outcome.

        :param command: the command to change.
        :param keys: its new keys.
        :param scope: its new scope.
        :returns: whether the change was made; ``False`` when the user cancelled it.
        """
        collisions = self.__model.collisions(command.id, keys, scope)
        if collisions and not self.confirm_reassign(collisions):
            return False
        self.__model.take_keys(command.id, keys, scope)
        self.__show_selected()
        return True

    def confirm_reassign(self, collisions: Sequence[tuple[Command, QKeySequence]]) -> bool:
        """Ask whether to take the colliding keys from the commands holding them -- a modal, so a test
        replaces this method rather than let it block.

        :param collisions: each other command and its key that would collide.
        :returns: whether the user chose to reassign.
        """
        lines = [f'"{keys_text([key])}" is already used by "{other.name}".' for other, key in collisions]
        others = ", ".join(dict.fromkeys(f'"{other.name}"' for other, _key in collisions))
        box = QMessageBox(QMessageBox.Icon.Warning, "Shortcut conflict", "\n".join(lines), parent=self)
        box.setInformativeText(f"Reassigning removes it from {others}.")
        reassign = box.addButton("Reassign", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is reassign

    def __refresh_editor_header(self, *_args: object) -> None:
        """Enable the editor's buttons by what each would change for the selected command."""
        command = self.__selected_command()
        if command is None:
            self.__editor_header.set_state(dirty=False, at_defaults=True)
            return
        saved = shared_shortcuts_settings().keymap
        draft = self.__model.draft()
        merged = self.__model.committed_with(saved, command.id)
        self.__editor_header.set_state(
            dirty=not self.__same_entry(command, draft, saved),
            at_defaults=draft.is_default(command),
            savable=not find_conflicts(self.__registry.commands(), merged),
        )

    @staticmethod
    def __same_entry(command: Command, first: Keymap, second: Keymap) -> bool:
        """Whether two keymaps give ``command`` the same keys and scope.

        :param command: the command.
        :param first: one keymap.
        :param second: the other.
        :returns: whether its entry is the same in both.
        """
        same_keys = first.effective_keys(command) == second.effective_keys(command)
        return same_keys and first.effective_scope(command) == second.effective_scope(command)

    # endregion
