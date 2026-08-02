"""The individual actions a list editor is built from -- each a self-contained `QAction` carrying its
own text, tooltip and shortcut, so any `ActionButtonColumn` can be given exactly the ones it needs.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget


def set_tooltip_and_shortcut(action: QAction, tooltip: str, shortcut: QKeySequence | None) -> None:
    """Set ``action``'s tooltip, naming its shortcut in it when it has one.

    The shortcut is set with `Qt.ShortcutContext.WidgetShortcut`, which is inert until the action is
    added to some widget with ``QWidget.addAction`` -- so it is the *owner* of the action, not the
    action, that decides which widget's focus arms it. That indirection is what lets a list editor arm
    these on its list alone, leaving an open in-place editor's own key handling untouched.

    :param action: the action to finish setting up.
    :param tooltip: what the action does, in words -- the shortcut is appended to it, since an
        icon-only button is otherwise the only place a user could discover the key.
    :param shortcut: the key that fires it, or ``None`` for an action with no shortcut.
    """
    if shortcut is not None:
        action.setShortcut(shortcut)
        action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        tooltip = f"{tooltip} ({shortcut.toString(QKeySequence.SequenceFormat.NativeText)})"
    action.setToolTip(tooltip)


class InsertItemAction(QAction):
    """Insert a new entry below the current one -- and the only way into an emptied list.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Insert", parent)
        set_tooltip_and_shortcut(self, "Insert a new entry below the current one", QKeySequence(Qt.Key.Key_Insert))


class EditItemAction(QAction):
    """Reopen the current entry for typing.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Edit", parent)
        set_tooltip_and_shortcut(self, "Edit the current entry", QKeySequence(Qt.Key.Key_F2))


class DeleteItemAction(QAction):
    """Drop the current entry.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Delete", parent)
        set_tooltip_and_shortcut(self, "Delete the current entry", QKeySequence(QKeySequence.StandardKey.Delete))


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
        set_tooltip_and_shortcut(
            self,
            "Move the current entry to the top",
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Home),
        )


class MoveUpItemAction(QAction):
    """Move the current entry one row up.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Move Up", parent)
        set_tooltip_and_shortcut(
            self,
            "Move the current entry up one place",
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Up),
        )


class MoveDownItemAction(QAction):
    """Move the current entry one row down.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Move Down", parent)
        set_tooltip_and_shortcut(
            self,
            "Move the current entry down one place",
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Down),
        )


class MoveToBottomItemAction(QAction):
    """Move the current entry to the last row.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Move to Bottom", parent)
        set_tooltip_and_shortcut(
            self,
            "Move the current entry to the bottom",
            QKeySequence(Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_End),
        )
