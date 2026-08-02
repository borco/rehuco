"""A vertical strip of icon-only tool buttons, one per action."""

from typing import Final

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget

from .item_actions import set_tooltip_and_shortcut


class ActionButtonColumn(QWidget):
    """A column of icon-only `QToolButton`s, each showing one `QAction` as its default action.

    A button here is a *view* of its action and holds no state of its own: enabling, the icon, the
    tooltip and the shortcut all live on the action, because a tool button showing a default action
    mirrors it and would undo anything set on the button directly at the next refresh. That is also
    what lets an app keep the icons recolored for the current theme (`ActionIconThemeHandler`)
    without this widget owning, or even knowing, an icon set.

    The column carries no icons at all: an action built by :meth:`add_action` has text, a tooltip and
    a shortcut, and its icon is the consuming app's to set. Until one is set the button draws blank
    -- deliberate, since a generic library guessing at a glyph is worse than an app supplying one.

    Sized to its buttons in both directions, so a caller lays it out beside a list without it
    stretching to the list's height; align it to the top of its layout cell to keep the first button
    level with the list's first row.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__layout: Final = QVBoxLayout(self)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def add_action(self, text: str, tooltip: str, shortcut: QKeySequence | None = None) -> QAction:
        """Build an action, append a button showing it, and hand the action back.

        The shortcut is set with `Qt.ShortcutContext.WidgetShortcut`, which is inert until the
        action is added to some widget with ``QWidget.addAction`` -- so it is the *owner* of the
        column, not the column, that decides which widget's focus arms it. That indirection is the
        point for a list editor: arming the shortcuts on the list itself means an open item editor
        (a `QLineEdit` child, focused in the list's stead) swallows ``Del`` as a character rather
        than firing the delete action.

        :param text: the action's name, shown in menus and read by accessibility tools; the buttons
            themselves are icon-only.
        :param tooltip: what the action does, in words -- the shortcut is appended to it, since an
            icon-only button is otherwise the only place a user could discover the key.
        :param shortcut: the key that fires it, or ``None`` for an action with no shortcut.
        :returns: the action, parented here, and the place its enabled state and icon live.
        """
        action = QAction(text, self)
        set_tooltip_and_shortcut(action, tooltip, shortcut)
        self.add_action_button(action)
        return action

    def add_action_button(self, action: QAction) -> QToolButton:
        """Append a button showing ``action`` to the bottom of the column.

        A button showing a default action mirrors its icon, text, tooltip and enabled state, but
        **not** its visibility -- Qt only auto-hides an action's proxy widgets in a menu or toolbar, not
        a `QToolButton` wired via `setDefaultAction`. Wiring `visibleChanged` here is what makes
        ``action.setVisible(False)`` actually hide the button, which is how a caller with no use for a
        particular action (a record editor with no default entries to restore) hides its button without
        this column needing any bespoke visibility API of its own.

        :param action: the action the button shows and triggers.
        :returns: the button, for a caller that needs to style or find it.
        """
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setVisible(action.isVisible())
        # visibleChanged() carries no argument -- it says only that isVisible() changed, not to what --
        # so the slot has to read it back rather than being handed it directly
        action.visibleChanged.connect(lambda: button.setVisible(action.isVisible()))
        self.__layout.addWidget(button)
        return button
