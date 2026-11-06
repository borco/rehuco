"""Tests for which keys a focused panel of the player keeps (#575, [[plugins#player-maximized]]).

The filter is driven with key events built by hand, so each rule is one press: an editor claims the player's keys as
they are bound now and nothing else, the tree and the rendered notes claim the plain navigation keys, and Esc in an
editor hands the keyboard back.
"""

# astroid reads a QAction's signals as the action's members
# pylint: disable=no-member

from unittest.mock import Mock

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QTreeView, QWidget
from pytest import fixture, mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.player_panel_keys import PlayerPanelKeys
from rehuco_agent.fields.widgets.markdown_edit import MarkdownEdit

PLAIN = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier


class Host:  # pylint: disable=too-few-public-methods
    """What the filter is built over: a parent, the player's actions with a few keys, and the hand-back it calls."""

    def __init__(self, qtbot: QtBot) -> None:
        self.parent = QWidget()
        qtbot.addWidget(self.parent)
        self.actions = [QAction(self.parent) for _ in range(6)]
        for action, keys in zip(self.actions, ("Space", "B", "Left", "F2", "Alt+V", "Shift+V")):
            action.setShortcut(QKeySequence(keys))
        self.on_escape = Mock()
        self.keys = PlayerPanelKeys(lambda: self.actions, self.on_escape, self.actions[3], self.parent)
        self.editor = MarkdownEdit(line_numbers=False, line_endings_visible=False, wrap_long_lines=True)
        self.tree = QTreeView()
        qtbot.addWidget(self.editor)
        qtbot.addWidget(self.tree)

    def press(self, widget: QWidget, kind: QEvent.Type, key: Qt.Key, modifiers: Qt.KeyboardModifier = PLAIN) -> bool:
        """Send a key event through the filter.

        :param widget: the widget it is for.
        :param kind: the event's type.
        :param key: the key.
        :param modifiers: the modifiers held.
        :returns: whether the filter consumed it.
        """
        return self.keys.eventFilter(widget, QKeyEvent(kind, key, modifiers))


@fixture(name="host")
def fixture_host(qtbot: QtBot) -> Host:
    """A filter over a player with five keys bound, the subtitle ones with Alt and Shift (#618).

    :param qtbot: pytest-qt fixture.
    :returns: the host.
    """
    return Host(qtbot)


@mark.parametrize(
    ("key", "modifiers", "claimed"),
    [
        param(Qt.Key.Key_Space, PLAIN, True, id="space"),
        param(Qt.Key.Key_B, PLAIN, True, id="a-player-key"),
        param(Qt.Key.Key_B, SHIFT, True, id="a-capital-of-one"),
        param(Qt.Key.Key_Left, PLAIN, True, id="an-arrow"),
        param(Qt.Key.Key_V, ALT, True, id="a-key-bound-with-alt"),
        param(Qt.Key.Key_V, SHIFT, True, id="a-key-bound-with-shift"),
        param(Qt.Key.Key_V, PLAIN, False, id="the-same-key-bare-is-not-bound-here"),
        param(Qt.Key.Key_X, PLAIN, False, id="a-key-the-player-does-not-use"),
        param(Qt.Key.Key_F2, PLAIN, False, id="the-key-that-ends-the-editing"),
        param(Qt.Key.Key_S, CTRL, False, id="another-shortcut"),
        param(Qt.Key.Key_Left, CTRL, False, id="a-key-with-a-modifier-the-player-does-not-bind"),
    ],
)
def test_an_editor_claims_the_players_keys_and_no_others(
    host: Host, key: Qt.Key, modifiers: Qt.KeyboardModifier, claimed: bool
) -> None:
    """**Test steps:**

    * send the editor a shortcut override for a key
    * verify it is claimed -- accepted and consumed -- only when it is one of the player's, with or without Shift
    """
    event = QKeyEvent(QEvent.Type.ShortcutOverride, key, modifiers)

    consumed = host.keys.eventFilter(host.editor, event)

    assert consumed is claimed
    assert event.isAccepted() is claimed


def test_an_editor_follows_a_key_rebound_on_the_shortcuts_page(host: Host) -> None:
    """**Test steps:**

    * rebind a player action to another key
    * verify the editor claims the new key and leaves the old one
    """
    host.actions[0].setShortcut(QKeySequence("X"))

    assert host.press(host.editor, QEvent.Type.ShortcutOverride, Qt.Key.Key_X)
    assert not host.press(host.editor, QEvent.Type.ShortcutOverride, Qt.Key.Key_Space)


@mark.parametrize(
    ("key", "modifiers", "claimed"),
    [
        param(Qt.Key.Key_Left, PLAIN, True, id="an-arrow"),
        param(Qt.Key.Key_Down, PLAIN, True, id="down"),
        param(Qt.Key.Key_Home, PLAIN, True, id="home"),
        param(Qt.Key.Key_PageDown, PLAIN, True, id="page-down"),
        param(Qt.Key.Key_Left, Qt.KeyboardModifier.KeypadModifier, True, id="a-keypad-arrow"),
        param(Qt.Key.Key_Space, PLAIN, False, id="space-stays-the-players"),
        param(Qt.Key.Key_B, PLAIN, False, id="b-stays-the-players"),
        param(Qt.Key.Key_Left, CTRL, False, id="a-ctrl-arrow-stays-the-players"),
    ],
)
def test_the_tree_claims_the_plain_navigation_keys_and_no_others(
    host: Host, key: Qt.Key, modifiers: Qt.KeyboardModifier, claimed: bool
) -> None:
    """**Test steps:**

    * send the tree a shortcut override for a key
    * verify it is claimed only when it is a plain arrow, Home, End, Page Up or Page Down
    """
    event = QKeyEvent(QEvent.Type.ShortcutOverride, key, modifiers)

    assert host.keys.eventFilter(host.tree, event) is claimed


def test_escape_in_an_editor_hands_the_keyboard_back_and_nowhere_else(host: Host) -> None:
    """**Test steps:**

    * press Esc in the editor and verify what Esc does there was done and the press was consumed
    * press Esc in the tree and verify it was left alone, so it reaches the maximized player
    * press Ctrl+Esc in the editor and verify it was left alone
    """
    assert host.press(host.editor, QEvent.Type.KeyPress, Qt.Key.Key_Escape)
    host.on_escape.assert_called_once_with()

    host.on_escape.reset_mock()
    assert not host.press(host.tree, QEvent.Type.KeyPress, Qt.Key.Key_Escape)
    assert not host.press(host.editor, QEvent.Type.KeyPress, Qt.Key.Key_Escape, CTRL)
    host.on_escape.assert_not_called()
