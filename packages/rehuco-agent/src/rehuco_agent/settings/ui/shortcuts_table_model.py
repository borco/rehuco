"""The Shortcuts page's table: every command with the keys and scope of the draft being edited (#344)."""

from collections.abc import Iterable
from typing import Any, Final, override

from borco_pyside.shortcuts import Command, CommandRegistry, CommandScope, Conflict, Keymap, find_conflicts, keys_text
from borco_pyside.shortcuts.keymap import keys_collide, scopes_overlap
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence
from PySide6.QtWidgets import QApplication

from ...fields.colors import ERROR_COLOR

type ModelIndex = QModelIndex | QPersistentModelIndex

COMMAND_COLUMN: Final = 0
KEYS_COLUMN: Final = 1
SCOPE_COLUMN: Final = 2
CONFLICT_COLUMN: Final = 3
COLUMN_TITLES: Final = ("Command", "Keys", "Scope", "Conflict")

KEYS_SEPARATOR: Final = "; "
"""Joins one command's keys in the Keys column; a comma would read as part of a chord."""

SEARCH_TEXT_ROLE: Final = Qt.ItemDataRole.UserRole
"""What a row answers to the search box: name, description, and its keys spelled natively and portably."""

COMMAND_ID_ROLE: Final = Qt.ItemDataRole.UserRole + 1
"""The row's command id."""


class ShortcutsTableModel(QAbstractTableModel):
    """One row per command of a registry, showing the **draft** keymap rather than the one in force.

    The draft is the page's working copy: :meth:`set_entry` and :meth:`take_keys` edit it, and the page
    commits it by handing :meth:`draft` back to the registry.

    Conflicts are recomputed with :func:`~borco_pyside.shortcuts.find_conflicts` after every edit, over the
    draft, so a row is badged the moment two commands collide -- the other command's row included.

    The rows never change, only what they show, so a wholesale replacement of the draft reports
    ``dataChanged`` for every cell rather than resetting the model: a reset drops the table's selection,
    and the editor beside it is following that selection.

    :param registry: the commands to list.
    :param parent: optional Qt parent.
    """

    draft_replaced = Signal()
    """Fires after :meth:`set_draft` -- not after an edit -- for whoever shows one command's draft."""

    def __init__(self, registry: CommandRegistry, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__commands: Final = registry.commands()
        self.__keymap = Keymap()
        self.__conflicts: list[Conflict] = []

    # region draft

    def set_draft(self, keymap: Keymap) -> None:
        """Replace the draft.

        :param keymap: the overrides to show; copied.
        """
        self.__keymap = keymap.copy()
        self.__refresh()
        self.draft_replaced.emit()

    def draft(self) -> Keymap:
        """The draft keymap, as an independent copy."""
        return self.__keymap.copy()

    def set_entry(self, command_id: str, keys: Iterable[QKeySequence], scope: CommandScope) -> None:
        """Edit one command's keys and scope; equal to its declaration, the override is dropped.

        :param command_id: the command being edited.
        :param keys: its keys, in order; a repeated one is kept once.
        :param scope: one of the command's allowed scopes.
        """
        command = self.__command(command_id)
        self.__keymap.set_keys(command, list(dict.fromkeys(keys)))
        self.__keymap.set_scope(command, scope)
        self.__refresh()

    def collisions(
        self, command_id: str, keys: Iterable[QKeySequence], scope: CommandScope
    ) -> list[tuple[Command, QKeySequence]]:
        """The other commands one command would collide with, were it given ``keys`` in ``scope``.

        :param command_id: the command about to change.
        :param keys: its prospective keys.
        :param scope: its prospective scope.
        :returns: each other command with its key that collides, in registration order.
        """
        command = self.__command(command_id)
        keys = tuple(keys)
        result: list[tuple[Command, QKeySequence]] = []
        for other in self.__commands:
            if other.id == command_id:
                continue
            other_scope = self.__keymap.effective_scope(other)
            if not scopes_overlap(command, scope, other, other_scope):
                continue
            for other_key in self.__keymap.effective_keys(other):
                if any(keys_collide(key, other_key) for key in keys):
                    result.append((other, other_key))
        return result

    def take_keys(self, command_id: str, keys: Iterable[QKeySequence], scope: CommandScope) -> None:
        """Give a command ``keys`` in ``scope``, removing every key that would collide from the other commands.

        :param command_id: the command being edited.
        :param keys: its keys.
        :param scope: its scope.
        """
        keys = tuple(keys)
        for other, other_key in self.collisions(command_id, keys, scope):
            remaining = [key for key in self.__keymap.effective_keys(other) if key != other_key]
            self.__keymap.set_keys(other, remaining)
        self.set_entry(command_id, keys, scope)

    def committed_with(self, saved: Keymap, command_id: str) -> Keymap:
        """``saved`` with one command's draft entry applied -- and, since that may take keys another command
        still holds there, the draft entries of the commands it collides with too, until nothing more
        changes.

        :param saved: the keymap in force.
        :param command_id: the command whose entry is being applied.
        :returns: the keymap a per-command Apply would save; it may still conflict if the draft does.
        """
        merged = saved.copy()
        pending = [command_id]
        done: set[str] = set()
        while pending:
            current = self.__command(pending.pop())
            done.add(current.id)
            merged.set_keys(current, self.__keymap.effective_keys(current))
            merged.set_scope(current, self.__keymap.effective_scope(current))
            for conflict in find_conflicts(self.__commands, merged):
                for involved in (conflict.first_id, conflict.second_id):
                    if involved not in done and involved not in pending:
                        pending.append(involved)
        return merged

    # endregion

    # region queries

    def command_at(self, row: int) -> Command:
        """The command a row shows.

        :param row: the row.
        :returns: its command.
        """
        return self.__commands[row]

    def row_of(self, command_id: str) -> int:
        """The row showing a command.

        :param command_id: the command's id.
        :returns: its row, or ``-1`` for an id no command has.
        """
        return next((row for row, command in enumerate(self.__commands) if command.id == command_id), -1)

    def keys_of(self, command_id: str) -> tuple[QKeySequence, ...]:
        """A command's keys under the draft.

        :param command_id: the command.
        :returns: its effective keys.
        """
        return self.__keymap.effective_keys(self.__command(command_id))

    def scope_of(self, command_id: str) -> CommandScope:
        """A command's scope under the draft.

        :param command_id: the command.
        :returns: its effective scope.
        """
        return self.__keymap.effective_scope(self.__command(command_id))

    def conflicts_of(self, command_id: str) -> list[tuple[Command, QKeySequence]]:
        """The other commands one command collides with.

        :param command_id: the command.
        :returns: each other command with the key it collides on, in registration order.
        """
        result: list[tuple[Command, QKeySequence]] = []
        for conflict in self.__conflicts:
            if command_id == conflict.first_id:
                result.append((self.__command(conflict.second_id), conflict.keys))
            elif command_id == conflict.second_id:
                result.append((self.__command(conflict.first_id), conflict.keys))
        return result

    def has_conflicts(self) -> bool:
        """Whether any two commands collide under the draft."""
        return bool(self.__conflicts)

    # endregion

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__commands)

    @override
    def columnCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(COLUMN_TITLES)

    @override
    def headerData(  # noqa: N802  (Qt API name)
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMN_TITLES[section]
        return None

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pylint: disable=too-many-return-statements
        if not index.isValid():
            return None
        command = self.__commands[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self.__text(command, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.__tooltip(command, column)
        if role == Qt.ItemDataRole.FontRole:
            if self.__keymap.is_default(command):
                return None
            font = QFont(QApplication.font())
            font.setBold(True)
            return font
        if role == Qt.ItemDataRole.ForegroundRole:
            if column == CONFLICT_COLUMN and self.conflicts_of(command.id):
                return QBrush(QColor(ERROR_COLOR))
            return None
        if role == SEARCH_TEXT_ROLE:
            return self.__search_text(command)
        if role == COMMAND_ID_ROLE:
            return command.id
        return None

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # endregion

    def __command(self, command_id: str) -> Command:
        """The command with an id.

        :param command_id: the id.
        :returns: the command.
        :raises KeyError: for an id no row has.
        """
        for command in self.__commands:
            if command.id == command_id:
                return command
        raise KeyError(command_id)

    def __text(self, command: Command, column: int) -> str:
        """What a cell shows.

        :param command: the row's command.
        :param column: the column.
        :returns: the cell text.
        """
        match column:
            case 0:
                return command.name
            case 1:
                return KEYS_SEPARATOR.join(keys_text([sequence]) for sequence in self.__keymap.effective_keys(command))
            case 2:
                return self.__keymap.effective_scope(command).label
            case _:
                return KEYS_SEPARATOR.join(other.name for other, _keys in self.conflicts_of(command.id))

    def __tooltip(self, command: Command, column: int) -> str | None:
        """A cell's tooltip: the command's description, or for the Conflict cell what it collides with.

        :param command: the row's command.
        :param column: the column.
        :returns: the tooltip, or ``None`` for none.
        """
        if column == CONFLICT_COLUMN:
            conflicts = self.conflicts_of(command.id)
            if not conflicts:
                return None
            return "\n".join(f"Conflicts with {other.name} on {keys_text([keys])}" for other, keys in conflicts)
        return command.description

    def __search_text(self, command: Command) -> str:
        """Everything the search box matches a row against.

        :param command: the row's command.
        :returns: name, description, and the effective keys spelled natively and portably, lower case.
        """
        keys = self.__keymap.effective_keys(command)
        return " ".join(
            (command.name, command.description, keys_text(keys), keys_text(keys, native=False), command.id)
        ).lower()

    def __refresh(self) -> None:
        """Recompute the conflicts and tell the views every cell may have changed."""
        self.__conflicts = find_conflicts(self.__commands, self.__keymap)
        if self.__commands:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.__commands) - 1, len(COLUMN_TITLES) - 1))


class ShortcutsFilterProxyModel(QSortFilterProxyModel):
    """Narrows the shortcuts table to the rows whose name, description or key text contains the search text,
    and sorts it.

    Also what sorts the table, by the clicked column's display text; sorting by no column (``-1``) gives back
    the order the commands were declared in.

    Neither the filter nor the sort is re-run on every ``dataChanged`` -- only when the text or the sort column
    changes -- so a row being edited neither vanishes because its new key no longer matches the search nor
    jumps away from under the user because its new key sorts elsewhere.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__filter_text = ""
        self.setDynamicSortFilter(False)

    def set_filter_text(self, text: str) -> None:
        """Show only the rows containing ``text``.

        :param text: the search text; blank shows every row.
        """
        self.__filter_text = text.strip().lower()
        self.invalidate()

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: ModelIndex) -> bool:  # noqa: N802  (Qt API name)
        if not self.__filter_text:
            return True
        model = self.sourceModel()
        text = model.index(source_row, 0, source_parent).data(SEARCH_TEXT_ROLE)
        return self.__filter_text in str(text)
