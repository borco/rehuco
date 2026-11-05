"""Which keys a focused panel of the player keeps for itself ([[plugins#player-maximized]], #575)."""

from collections.abc import Callable, Iterable
from typing import Final, cast, override

from PySide6.QtCore import QEvent, QKeyCombination, QObject, Qt
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QWidget

from ..fields.widgets.markdown_edit import MarkdownEdit

SHIFT: Final = Qt.KeyboardModifier.ShiftModifier.value

NAVIGATION_KEYS: Final = frozenset(
    {
        Qt.Key.Key_Left,
        Qt.Key.Key_Right,
        Qt.Key.Key_Up,
        Qt.Key.Key_Down,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
        Qt.Key.Key_PageUp,
        Qt.Key.Key_PageDown,
    }
)
"""What the tree and the rendered notes do with the keys that have no modifier: move through the rows or the text. The
player seeks and changes the volume with the arrows; there they move the selection."""


class PlayerPanelKeys(QObject):
    """Decides, for the widgets of the player's panels, which keys are theirs and which stay the player's.

    The player's keys are shortcuts armed on everything inside it, the panels included, and a shortcut is tried before
    the focused widget sees the key. So **a panel claims the keys it needs** by accepting the shortcut-override event
    Qt sends first (the precedent is :class:`~borco_pyside.widgets.key_sequence_recorder.KeySequenceRecorder`'s):

    * **A notes editor claims every key that is one of the player's**, as they are bound now, so everything types and
      a key rebound on the Shortcuts page follows -- bar the one that ends editing (F2), which must still answer.
      Other shortcuts (``Ctrl+S``) are left alone. **Esc** ends the editing and hands the keyboard back to the
      player (:paramref:`on_escape`), which the editor would otherwise eat; the next Esc is the player's.
    * **The tree and the rendered notes claim the plain arrows, Home, End, Page Up and Page Down** alone: Space, ``B``,
      ``I``, ``T``, ``N``, ``[``, ``]`` and the Ctrl arrows stay the player's.

    :param actions: the player's actions, read at each press so a rebound key is the current one.
    :param on_escape: what Esc does in an editor: ends the editing and puts the keyboard on the player.
    :param ends_editing: the action that ends editing, whose keys an editor leaves to it.
    :param parent: the Qt parent, which owns this.
    """

    def __init__(
        self,
        actions: Callable[[], Iterable[QAction]],
        on_escape: Callable[[], None],
        ends_editing: QAction,
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self.__actions: Final = actions
        self.__on_escape: Final = on_escape
        self.__ends_editing: Final = ends_editing

    def watch(self, root: QWidget) -> None:
        """Filter the keys of a panel's widgets.

        :param root: the panel; it and everything in it, at this moment, is watched.
        """
        for widget in (root, *root.findChildren(QWidget)):
            widget.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        """Claim the keys a panel keeps, hand Esc in an editor back to the player.

        :param watched: a widget of a panel.
        :param event: what happened to it.
        :returns: whether the event is consumed.
        """
        kind = event.type()
        if kind not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        key_event = cast(QKeyEvent, event)
        in_editor = self.__in_editor(watched)
        if kind == QEvent.Type.KeyPress:
            if in_editor and key_event.key() == Qt.Key.Key_Escape and not self.__modifiers(key_event):
                self.__on_escape()
                return True
            return False
        claimed = self.__plays(key_event) if in_editor else self.__navigates(key_event)
        if claimed:
            event.accept()
        return claimed

    @staticmethod
    def __in_editor(widget: QObject) -> bool:
        """Whether a widget is a notes editor, or inside one (its viewport).

        :param widget: the widget.
        :returns: whether it is.
        """
        node: QObject | None = widget
        while node is not None:
            if isinstance(node, MarkdownEdit):
                return True
            node = node.parent()
        return False

    @staticmethod
    def __modifiers(event: QKeyEvent) -> Qt.KeyboardModifier:
        """The modifiers of a press, without the keypad's, which says where the key is and not what it does.

        :param event: the press.
        :returns: the modifiers.
        """
        return Qt.KeyboardModifier(event.modifiers().value & ~Qt.KeyboardModifier.KeypadModifier.value)

    def __plays(self, event: QKeyEvent) -> bool:
        """Whether the press is one of the player's keys, with or without Shift: a capital typed is never a command.

        :param event: the press.
        :returns: whether it is.
        """
        modifiers, key = self.__modifiers(event), Qt.Key(event.key())
        keys = {
            QKeySequence(QKeyCombination(modifiers, key)),
            QKeySequence(QKeyCombination(Qt.KeyboardModifier(modifiers.value & ~SHIFT), key)),
        }
        return any(
            shortcut in keys
            for action in self.__actions()
            if action is not self.__ends_editing
            for shortcut in action.shortcuts()
        )

    def __navigates(self, event: QKeyEvent) -> bool:
        """Whether the press moves through the rows or the text of a tree or a rendered note.

        :param event: the press.
        :returns: whether it is a plain arrow, Home, End, Page Up or Page Down.
        """
        return not self.__modifiers(event) and Qt.Key(event.key()) in NAVIGATION_KEYS
