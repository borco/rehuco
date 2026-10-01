"""The individual actions a list editor is built from -- each a self-contained `QAction` carrying its
own text, tooltip and shortcut, so any `ActionButtonColumn` can be given exactly the ones it needs.

Each keyed action fires one of the :data:`LIST_EDITOR_COMMANDS`, so a host that installs a
:class:`~borco_pyside.shortcuts.CommandRegistry` holding them rebinds every list editor's keys from its
keymap; a host that installs none gets the commands' defaults, exactly as before there was a keymap.
"""

from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from ..shortcuts import Command, CommandRegistry, CommandScope, KeySpec

LIST_EDITOR_FOCUS_GROUP: Final = "list_editor"
"""The focus group every list-editor command shares: their keys only ever reach a list editor's list."""


def list_editor_command(command_id: str, name: str, description: str, key: KeySpec) -> Command:
    """One list-editor command: armed on the list it is added to alone (`CommandScope.WIDGET`), in the
    :data:`LIST_EDITOR_FOCUS_GROUP`.

    :param command_id: the command's id.
    :param name: its label.
    :param description: what it does -- also the action's tooltip.
    :param key: its default key.
    :returns: the command.
    """
    return Command(command_id, name, description, (key,), (CommandScope.WIDGET,), focus_group=LIST_EDITOR_FOCUS_GROUP)


INSERT_ITEM_COMMAND: Final = list_editor_command(
    "list_editor.insert", "Insert entry", "Insert a new entry below the current one", Qt.Key.Key_Insert
)
DUPLICATE_ITEM_COMMAND: Final = list_editor_command(
    "list_editor.duplicate",
    "Duplicate entry",
    "Duplicate the current entry below itself",
    Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_D,
)
EDIT_ITEM_COMMAND: Final = list_editor_command(
    "list_editor.edit", "Edit entry", "Edit the current entry", Qt.Key.Key_F2
)
DELETE_ITEM_COMMAND: Final = list_editor_command(
    "list_editor.delete", "Delete entry", "Delete the current entry", QKeySequence.StandardKey.Delete
)
MOVE_TO_TOP_ITEM_COMMAND: Final = list_editor_command(
    "list_editor.move_to_top",
    "Move entry to top",
    "Move the current entry to the top",
    Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Home,
)
MOVE_UP_ITEM_COMMAND: Final = list_editor_command(
    "list_editor.move_up",
    "Move entry up",
    "Move the current entry up one place",
    Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Up,
)
MOVE_DOWN_ITEM_COMMAND: Final = list_editor_command(
    "list_editor.move_down",
    "Move entry down",
    "Move the current entry down one place",
    Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Down,
)
MOVE_TO_BOTTOM_ITEM_COMMAND: Final = list_editor_command(
    "list_editor.move_to_bottom",
    "Move entry to bottom",
    "Move the current entry to the bottom",
    Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_End,
)

LIST_EDITOR_COMMANDS: Final = (
    INSERT_ITEM_COMMAND,
    DUPLICATE_ITEM_COMMAND,
    EDIT_ITEM_COMMAND,
    DELETE_ITEM_COMMAND,
    MOVE_TO_TOP_ITEM_COMMAND,
    MOVE_UP_ITEM_COMMAND,
    MOVE_DOWN_ITEM_COMMAND,
    MOVE_TO_BOTTOM_ITEM_COMMAND,
)
"""Every keyed list-editor action's command, for a host to register in its own registry."""


def set_tooltip_and_shortcut(
    action: QAction, tooltip: str, shortcut: QKeySequence | None, *, command_id: str | None = None
) -> None:
    """Set ``action``'s tooltip, naming its shortcut in it when it has one.

    The shortcut is set with `Qt.ShortcutContext.WidgetShortcut`, which is inert until the action is
    added to some widget with ``QWidget.addAction`` -- so it is the *owner* of the action, not the
    action, that decides which widget's focus arms it. That indirection is what lets a list editor arm
    these on its list alone, leaving an open in-place editor's own key handling untouched.

    Given a ``command_id`` the installed :class:`~borco_pyside.shortcuts.CommandRegistry` knows, the action
    is bound to that command instead and ``shortcut`` goes unused: the keys and their scope are the
    keymap's, and the tooltip follows them. Without one -- no id, no registry, or an id it does not hold --
    nothing differs from a plain literal shortcut.

    :param action: the action to finish setting up.
    :param tooltip: what the action does, in words -- the shortcut is appended to it, since an
        icon-only button is otherwise the only place a user could discover the key.
    :param shortcut: the key that fires it, or ``None`` for an action with no shortcut.
    :param command_id: the command the action fires, if it has one.
    """
    registry = CommandRegistry.installed()
    if command_id is not None and registry is not None and registry.has(command_id):
        registry.bind(action, command_id, tooltip=tooltip)
        return
    if shortcut is not None:
        action.setShortcut(shortcut)
        action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        tooltip = f"{tooltip} ({shortcut.toString(QKeySequence.SequenceFormat.NativeText)})"
    action.setToolTip(tooltip)


def set_command(action: QAction, command: Command, tooltip: str | None = None) -> None:
    """Set ``action`` up as ``command``'s, through :func:`set_tooltip_and_shortcut`: its first default key
    as the literal fallback.

    :param action: the action to finish setting up.
    :param command: the command it fires.
    :param tooltip: what it does, in words; defaults to the command's description.
    """
    set_tooltip_and_shortcut(
        action,
        tooltip if tooltip is not None else command.description,
        QKeySequence(command.default_keys[0]),
        command_id=command.id,
    )


class InsertItemAction(QAction):
    """Insert a new entry below the current one -- and the only way into an emptied list.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Insert", parent)
        set_command(self, INSERT_ITEM_COMMAND)


class DuplicateItemAction(QAction):
    """Insert a copy of the current entry below it -- the way a variant of an existing entry is written.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Duplicate", parent)
        set_command(self, DUPLICATE_ITEM_COMMAND)


class EditItemAction(QAction):
    """Reopen the current entry for typing.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Edit", parent)
        set_command(self, EDIT_ITEM_COMMAND)


class DeleteItemAction(QAction):
    """Drop the current entry.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Delete", parent)
        set_command(self, DELETE_ITEM_COMMAND)


class ResetItemAction(QAction):
    """Replace the whole list with its defaults -- list-wide, so it carries no shortcut of its own.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Reset", parent)
        self.setToolTip("Replace the list with the default entries")


class MoveToTopItemAction(QAction):
    """Move the current entry to the first row.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Move to Top", parent)
        set_command(self, MOVE_TO_TOP_ITEM_COMMAND)


class MoveUpItemAction(QAction):
    """Move the current entry one row up.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Move Up", parent)
        set_command(self, MOVE_UP_ITEM_COMMAND)


class MoveDownItemAction(QAction):
    """Move the current entry one row down.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Move Down", parent)
        set_command(self, MOVE_DOWN_ITEM_COMMAND)


class MoveToBottomItemAction(QAction):
    """Move the current entry to the last row.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Move to Bottom", parent)
        set_command(self, MOVE_TO_BOTTOM_ITEM_COMMAND)
